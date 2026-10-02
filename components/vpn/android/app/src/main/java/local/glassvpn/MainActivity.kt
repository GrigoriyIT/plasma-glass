package local.glassvpn

import android.Manifest
import android.content.ClipboardManager
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlin.concurrent.thread

class MainActivity : ComponentActivity() {
    companion object {
        const val EXTRA_CONNECT = "connect"
    }

    private lateinit var store: Store
    private var servers by mutableStateOf(listOf<Server>())
    private var selected by mutableStateOf<String?>(null)
    private var latency by mutableStateOf(mapOf<String, Int?>())
    private var busy by mutableStateOf(false)
    private var checks by mutableStateOf(listOf<Check>())
    private var vpnApps by mutableStateOf(listOf<VpnApp>())
    private enum class Page { MAIN, CHECK, SETTINGS, APPS }
    private var page by mutableStateOf(Page.MAIN)
    private val removeQueue = ArrayDeque<VpnApp>()

    // one system uninstall dialog after another for "remove all"
    private val removal: androidx.activity.result.ActivityResultLauncher<Intent> = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        refreshChecks()
        removeQueue.removeFirstOrNull()?.let { launchRemove(it) }
    }

    private val vpnConsent = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        if (VpnService.prepare(this) == null) GlassVpnService.start(this)
    }
    private val notifyPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        store = Store(this)
        reload()
        if (android.os.Build.VERSION.SDK_INT >= 33) notifyPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        handle(intent)
        // auto-connect when the user opens the app (not on rotation, not from a share/tile intent)
        if (savedInstanceState == null && intent?.action == Intent.ACTION_MAIN && store.autoConnect &&
            store.servers.isNotEmpty() && GlassVpnService.status.value.state == VpnState.OFF) connect()
        setContent {
            val dark = isSystemInDarkTheme()
            MaterialTheme(colorScheme = if (dark) darkColorScheme() else lightColorScheme()) {
                val st by GlassVpnService.status.collectAsStateWithLifecycle()
                when (page) {
                    Page.MAIN -> Screen(st, dark)
                    Page.CHECK -> CheckScreen(dark)
                    Page.SETTINGS -> SettingsScreen(dark, store, onBack = { page = Page.MAIN },
                                                    onApps = { page = Page.APPS }, open = ::open)
                    Page.APPS -> AppsScreen(dark, store) { changed ->
                        page = Page.SETTINGS
                        // the exclusion list is fixed when the TUN is built: rebuild it
                        if (changed && GlassVpnService.status.value.state != VpnState.OFF) GlassVpnService.start(this)
                    }
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        refreshChecks()   // back from a settings screen or an uninstall dialog
    }

    private fun refreshChecks() {
        vpnApps = otherVpnApps(this)
        checks = networkChecks(this, GlassVpnService.status.value.state != VpnState.OFF)
    }

    private fun open(intent: Intent) {
        try {
            startActivity(intent)
        } catch (e: android.content.ActivityNotFoundException) {   // OEMs drop some settings screens
            startActivity(Intent(Settings.ACTION_SETTINGS))
        }
    }

    private fun launchRemove(app: VpnApp) {
        try {
            removal.launch(removeIntent(app))
        } catch (e: android.content.ActivityNotFoundException) {
            toast("Не удалось открыть удаление ${app.label}")
        }
    }

    private fun removeAll() {
        removeQueue.clear()
        removeQueue.addAll(vpnApps.filter { !it.system })
        removeQueue.removeFirstOrNull()?.let { launchRemove(it) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    private fun handle(intent: Intent?) {
        when (intent?.action) {
            Intent.ACTION_SEND -> intent.getStringExtra(Intent.EXTRA_TEXT)?.let(::add)
            Intent.ACTION_VIEW -> intent.dataString?.let(::add)
        }
        if (intent?.getBooleanExtra(EXTRA_CONNECT, false) == true) connect()
    }

    private fun reload() {
        servers = store.servers
        selected = store.current()?.name
        latency = store.latency
    }

    private fun toast(msg: String) = runOnUiThread { Toast.makeText(this, msg, Toast.LENGTH_LONG).show() }

    private fun connect() {
        if (store.servers.isEmpty()) return toast("Сначала добавьте подписку или ключ")
        val consent = VpnService.prepare(this)
        if (consent != null) vpnConsent.launch(consent) else GlassVpnService.start(this)
    }

    private fun toggle(state: VpnState) {
        if (state == VpnState.OFF) connect() else GlassVpnService.start(this, GlassVpnService.ACTION_DISCONNECT)
    }

    private fun select(name: String) {
        store.selected = name
        selected = name
        if (GlassVpnService.status.value.state != VpnState.OFF) GlassVpnService.start(this)
    }

    private fun background(work: () -> String?) {
        busy = true
        thread {
            val msg = work()
            runOnUiThread { busy = false; reload(); msg?.let(::toast) }
        }
    }

    private fun add(text: String) = background {
        val keys = text.lines().count { parseVless(it.trim()) != null }
        when {
            store.addInput(text) -> store.updateSubscriptions()
            keys == 0 -> "Не найдено ни подписки, ни ключа vless://"
            else -> "Добавлено ключей: $keys"
        }
    }

    private fun testLatency() = background {
        val res = java.util.concurrent.ConcurrentHashMap<String, Int>()
        val tested = store.servers.map { s ->
            thread { tcpLatency(s.host, s.port)?.let { res[s.name] = it } }.let { s.name to it }
        }
        tested.forEach { it.second.join() }
        store.latency = tested.associate { (name, _) -> name to res[name] }
        null
    }

    // ------------------------------------------------------------------ UI --

    @Composable
    private fun Screen(st: VpnStatus, dark: Boolean) {
        var adding by remember { mutableStateOf(false) }
        var menu by remember { mutableStateOf(false) }
        val bg = if (dark) listOf(Color(0xFF0E1726), Color(0xFF1B1530), Color(0xFF0B1F24))
                 else listOf(Color(0xFFDDE8FF), Color(0xFFF3E6FF), Color(0xFFDDF6F0))
        Box(Modifier.fillMaxSize().background(Brush.linearGradient(bg))) {
            Column(Modifier.fillMaxSize().systemBarsPadding().padding(horizontal = 16.dp)) {
                Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("Glass VPN", fontSize = 22.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    IconButton(onClick = { adding = true }) { Icon(Icons.Filled.Add, "Добавить") }
                    IconButton(onClick = { background { store.updateSubscriptions() } }, enabled = !busy) {
                        Icon(Icons.Filled.Refresh, "Обновить подписки")
                    }
                    Box {
                        IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, "Ещё") }
                        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                            DropdownMenuItem(text = { Text("Проверка сети и других VPN") },
                                             onClick = { menu = false; page = Page.CHECK })
                            DropdownMenuItem(text = { Text("Настройки") },
                                             onClick = { menu = false; page = Page.SETTINGS })
                            DropdownMenuItem(text = { Text("Проверить задержку") },
                                             onClick = { menu = false; testLatency() })
                            DropdownMenuItem(text = { Text("Удалить все серверы") }, onClick = {
                                menu = false
                                store.subscriptions = emptyList(); store.servers = emptyList(); store.latency = emptyMap()
                                reload()
                            })
                        }
                    }
                }

                Spacer(Modifier.height(24.dp))
                ShieldButton(st.state, dark) { toggle(st.state) }
                Spacer(Modifier.height(16.dp))
                Text(STATE_TEXT[st.state]!!.replaceFirstChar { it.uppercase() }, fontSize = 20.sp,
                     fontWeight = FontWeight.Medium, modifier = Modifier.align(Alignment.CenterHorizontally))
                val detail = when (st.state) {
                    VpnState.ON -> listOfNotNull(st.server, st.latency?.let { "$it мс" }).joinToString(" · ") +
                                   "\n↓ ${humanRate(st.down)}   ↑ ${humanRate(st.up)}"
                    VpnState.ERROR -> st.message ?: st.server
                    VpnState.CONNECTING -> st.server
                    VpnState.OFF -> selected ?: "Добавьте подписку"
                }
                if (st.state != VpnState.OFF && st.since != 0L) ConnectedFor(st.since)
                Text(detail, fontSize = 14.sp, color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.65f),
                     textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                     modifier = Modifier.align(Alignment.CenterHorizontally).padding(top = 4.dp))

                val problems = vpnApps.size + checks.count { it.level != Level.OK }
                if (problems > 0) {
                    Spacer(Modifier.height(16.dp))
                    Glass(dark, Modifier.align(Alignment.CenterHorizontally).clickable { page = Page.CHECK }) {
                        Text("⚠  Найдено проблем: $problems — проверить", fontSize = 14.sp,
                             modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp))
                    }
                }
                Spacer(Modifier.height(24.dp))
                if (busy) LinearProgressIndicator(Modifier.fillMaxWidth().padding(bottom = 8.dp))
                Glass(dark, Modifier.fillMaxWidth().weight(1f).padding(bottom = 16.dp)) {
                    if (servers.isEmpty()) {
                        Text("Нет серверов.\nНажмите «+» и вставьте ссылку на подписку или ключи vless://",
                             Modifier.padding(20.dp), color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f))
                    }
                    LazyColumn {
                        items(servers, key = { it.name }) { s -> ServerRow(s, s.name == selected, latency, dark) }
                    }
                }
            }
        }
        if (adding) AddDialog(onDismiss = { adding = false }) { adding = false; add(it) }
    }

    @Composable
    private fun CheckScreen(dark: Boolean) {
        androidx.activity.compose.BackHandler { page = Page.MAIN }
        val dim = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
        val bg = if (dark) listOf(Color(0xFF0E1726), Color(0xFF1B1530), Color(0xFF0B1F24))
                 else listOf(Color(0xFFDDE8FF), Color(0xFFF3E6FF), Color(0xFFDDF6F0))
        Box(Modifier.fillMaxSize().background(Brush.linearGradient(bg))) {
            LazyColumn(Modifier.fillMaxSize().systemBarsPadding().padding(horizontal = 16.dp),
                       verticalArrangement = Arrangement.spacedBy(12.dp)) {
                item {
                    Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        IconButton(onClick = { page = Page.MAIN }) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад")
                        }
                        Text("Проверка сети", fontSize = 22.sp, fontWeight = FontWeight.SemiBold,
                             modifier = Modifier.weight(1f))
                        IconButton(onClick = { refreshChecks() }) { Icon(Icons.Filled.Refresh, "Проверить снова") }
                    }
                }
                item {
                    Glass(dark, Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(12.dp)) {
                            Text("Другие VPN-приложения", fontWeight = FontWeight.Medium, fontSize = 16.sp)
                            if (vpnApps.isEmpty()) {
                                Text("Не найдено", color = dim, fontSize = 14.sp, modifier = Modifier.padding(top = 4.dp))
                            } else {
                                Text("Они могут перехватывать трафик, включать свою «постоянную VPN» или оставлять " +
                                     "прокси. Удаление подтверждается в системном окне.",
                                     color = dim, fontSize = 13.sp, modifier = Modifier.padding(vertical = 4.dp))
                                for (app in vpnApps) Row(Modifier.fillMaxWidth().padding(vertical = 2.dp),
                                                         verticalAlignment = Alignment.CenterVertically) {
                                    Column(Modifier.weight(1f)) {
                                        Text(app.label, fontSize = 15.sp)
                                        if (app.system) Text("встроенное — можно только отключить", color = dim, fontSize = 12.sp)
                                    }
                                    TextButton(onClick = { launchRemove(app) }) {
                                        Text(if (app.system) "Отключить" else "Удалить")
                                    }
                                }
                                if (vpnApps.count { !it.system } > 1) {
                                    Button(onClick = { removeAll() }, modifier = Modifier.padding(top = 4.dp)) {
                                        Text("Удалить все (${vpnApps.count { !it.system }})")
                                    }
                                }
                            }
                        }
                    }
                }
                item {
                    Glass(dark, Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(12.dp)) {
                            Text("Настройки сети", fontWeight = FontWeight.Medium, fontSize = 16.sp)
                            for (c in checks) Row(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                                Box(Modifier.padding(top = 6.dp).size(10.dp).clip(CircleShape).background(Color(stateColor(when (c.level) {
                                    Level.OK -> VpnState.ON
                                    Level.WARN -> VpnState.CONNECTING
                                    Level.BAD -> VpnState.ERROR
                                }))))
                                Spacer(Modifier.width(12.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(c.title, fontSize = 15.sp)
                                    Text(c.detail, color = dim, fontSize = 13.sp)
                                    if (c.fix != null && c.fixLabel != null) {
                                        TextButton(onClick = { open(c.fix) },
                                                   contentPadding = PaddingValues(0.dp)) { Text(c.fixLabel) }
                                    }
                                }
                            }
                        }
                    }
                }
                item {
                    Glass(dark, Modifier.fillMaxWidth().padding(bottom = 16.dp)) {
                        Column(Modifier.padding(12.dp)) {
                            Text("Сбросить сеть к стандартным настройкам", fontWeight = FontWeight.Medium, fontSize = 16.sp)
                            Text("Если после других VPN что-то осталось сломано. Android не даёт приложениям " +
                                 "делать это самим — откроются настройки:\n$RESET_HINT",
                                 color = dim, fontSize = 13.sp, modifier = Modifier.padding(vertical = 4.dp))
                            TextButton(onClick = { open(Intent(Settings.ACTION_SETTINGS)) }) { Text("Открыть настройки") }
                        }
                    }
                }
            }
        }
    }

    @Composable
    private fun ServerRow(s: Server, isSelected: Boolean, lat: Map<String, Int?>, dark: Boolean) {
        val tint = if (isSelected) (if (dark) Color.White.copy(alpha = 0.10f) else Color.White.copy(alpha = 0.55f))
                   else Color.Transparent
        Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(tint)
                .clickable { select(s.name) }.padding(horizontal = 16.dp, vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically) {
            RadioButton(selected = isSelected, onClick = { select(s.name) }, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(s.name, maxLines = 1, overflow = TextOverflow.Ellipsis, fontSize = 15.sp)
                Text("${s.type} · ${s.security}" + if (s.encryption != "none") " · pq" else "",
                     fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f))
            }
            if (s.name in lat) {
                val ms = lat[s.name]
                Text(ms?.let { "$it мс" } ?: "—", fontSize = 13.sp,
                     color = when {
                         ms == null -> Color(stateColor(VpnState.ERROR))
                         ms < 150 -> Color(stateColor(VpnState.ON))
                         else -> Color(stateColor(VpnState.CONNECTING))
                     })
            }
        }
    }

    @Composable
    private fun AddDialog(onDismiss: () -> Unit, onAdd: (String) -> Unit) {
        var text by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = onDismiss,
            title = { Text("Подписка или ключ") },
            text = {
                Column {
                    Text("Ссылка на подписку (https://…) или ключи vless:// — по одному в строке",
                         fontSize = 13.sp, modifier = Modifier.padding(bottom = 8.dp))
                    OutlinedTextField(text, { text = it }, Modifier.fillMaxWidth().heightIn(min = 120.dp))
                    TextButton(onClick = {
                        val clip = getSystemService(ClipboardManager::class.java).primaryClip
                        clip?.getItemAt(0)?.coerceToText(this@MainActivity)?.let { text = it.toString() }
                    }) { Text("Вставить из буфера") }
                }
            },
            confirmButton = { TextButton(onClick = { onAdd(text) }, enabled = text.isNotBlank()) { Text("Добавить") } },
            dismissButton = { TextButton(onClick = onDismiss) { Text("Отмена") } },
        )
    }
}

/** "Connected for 1:02:03", ticking once a second. */
@Composable
private fun ColumnScope.ConnectedFor(since: Long) {
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(since) {
        while (true) { now = System.currentTimeMillis(); kotlinx.coroutines.delay(1000 - now % 1000) }
    }
    Text(elapsed(now - since), fontSize = 28.sp, fontWeight = FontWeight.Light,
         style = androidx.compose.ui.text.TextStyle(fontFeatureSettings = "tnum"),   // digits don't jitter
         modifier = Modifier.align(Alignment.CenterHorizontally).padding(top = 2.dp))
}

internal fun elapsed(ms: Long): String {
    val t = (ms / 1000).coerceAtLeast(0)
    val d = t / 86400
    val hms = "%d:%02d:%02d".format(t / 3600 % 24, t / 60 % 60, t % 60)
    return if (d > 0) "$d д $hms" else hms
}

@Composable
internal fun Glass(dark: Boolean, modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val shape = RoundedCornerShape(24.dp)
    Column(modifier.clip(shape)
        .background(if (dark) Color.White.copy(alpha = 0.06f) else Color.White.copy(alpha = 0.45f))
        .border(BorderStroke(1.dp, if (dark) Color.White.copy(alpha = 0.12f) else Color.White.copy(alpha = 0.8f)), shape)
        .padding(6.dp), content = content)
}

/** The tray icon, large: a shield plus a status dot (none = off, pulsing amber = connecting). */
@Composable
private fun ColumnScope.ShieldButton(state: VpnState, dark: Boolean, onClick: () -> Unit) {
    val pulse by rememberInfiniteTransition(label = "pulse").animateFloat(
        0.35f, 1f, infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "a")
    val ring by animateColorAsState(
        if (state == VpnState.OFF) Color.White.copy(alpha = if (dark) 0.15f else 0.7f) else Color(stateColor(state)),
        label = "ring")
    val fg = if (dark) Color.White else Color(0xFF1C1C1E)
    Box(Modifier.align(Alignment.CenterHorizontally).size(180.dp).clip(CircleShape)
            .background(Brush.radialGradient(
                if (dark) listOf(Color.White.copy(alpha = 0.14f), Color.White.copy(alpha = 0.04f))
                else listOf(Color.White.copy(alpha = 0.9f), Color.White.copy(alpha = 0.4f))))
            .border(3.dp, ring.copy(alpha = if (state == VpnState.CONNECTING) pulse else ring.alpha), CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center) {
        Canvas(Modifier.size(84.dp)) {
            val w = size.width
            val h = size.height
            val shield = Path().apply {
                moveTo(w * 0.5f, h * 0.04f)
                lineTo(w * 0.88f, h * 0.18f)
                cubicTo(w * 0.88f, h * 0.55f, w * 0.75f, h * 0.80f, w * 0.5f, h * 0.96f)
                cubicTo(w * 0.25f, h * 0.80f, w * 0.12f, h * 0.55f, w * 0.12f, h * 0.18f)
                close()
            }
            drawPath(shield, fg, style = Stroke(width = w * 0.075f, join = StrokeJoin.Round))
            if (state != VpnState.OFF) {
                val c = Color(stateColor(state))
                drawCircle(c.copy(alpha = if (state == VpnState.CONNECTING) pulse else 1f),
                           radius = w * 0.14f, center = Offset(w * 0.5f, h * 0.48f))
            }
        }
    }
}
