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
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.focus.focusRequester
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
    private val tv by lazy { isTv(this) }
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
        // light status/navigation bar icons on the dark glass
        enableEdgeToEdge(androidx.activity.SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
                         androidx.activity.SystemBarStyle.dark(android.graphics.Color.TRANSPARENT))
        store = Store(this)
        reload()
        if (android.os.Build.VERSION.SDK_INT >= 33) notifyPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        handle(intent)
        // auto-connect when the user opens the app (not on rotation, not from a share/tile intent)
        if (savedInstanceState == null && intent?.action == Intent.ACTION_MAIN && store.autoConnect &&
            store.servers.isNotEmpty() && GlassVpnService.status.value.state == VpnState.OFF) connect()
        setContent {
            val dark = true   // the glass look is dark by design
            MaterialTheme(colorScheme = GlassColors.Colors) {
              // text and icons outside a Material Surface default to black: make them glass-white
              CompositionLocalProvider(LocalContentColor provides GlassColors.Text) {
                val st by GlassVpnService.status.collectAsStateWithLifecycle()
                when (page) {
                    Page.MAIN -> if (tv) TvScreen(st, dark) else Screen(st, dark)
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
        // an ERROR with a message means the service gave up (no servers, no permission…): try again
        val stopped = state == VpnState.OFF || (state == VpnState.ERROR && GlassVpnService.status.value.message != null)
        if (stopped) connect() else GlassVpnService.start(this, GlassVpnService.ACTION_DISCONNECT)
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
        Backdrop {
            Column(Modifier.fillMaxSize().systemBarsPadding().padding(horizontal = 18.dp)) {
                Row(Modifier.fillMaxWidth().padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Wordmark(24.sp, Modifier.weight(1f))
                    RoundGlassButton(Icons.Filled.Add, "Добавить") { adding = true }
                    Spacer(Modifier.width(8.dp))
                    RoundGlassButton(Icons.Filled.Refresh, "Обновить подписки") { background { store.updateSubscriptions() } }
                    Spacer(Modifier.width(8.dp))
                    Box {
                        RoundGlassButton(Icons.Filled.MoreVert, "Ещё") { menu = true }
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
                Spacer(Modifier.height(36.dp))
                Box(Modifier.align(Alignment.CenterHorizontally)) { GlassOrb(st.state, Modifier, 190.dp) { toggle(st.state) } }
                Spacer(Modifier.height(22.dp))
                StatusBlock(st)
                ProblemsChip()
                Spacer(Modifier.height(20.dp))
                if (busy) LinearProgressIndicator(Modifier.fillMaxWidth().padding(bottom = 8.dp), color = GlassColors.Accent)
                ServerCard(Modifier.fillMaxWidth().weight(1f).padding(bottom = 16.dp),
                           "Нажмите «+» и вставьте ссылку на подписку или ключи vless://")
            }
        }
        if (adding) AddDialog(onDismiss = { adding = false }) { adding = false; add(it) }
    }

    @Composable
    private fun ColumnScope.ProblemsChip() {
        val problems = vpnApps.size + checks.count { it.isProblem }
        if (problems == 0) return
        Spacer(Modifier.height(14.dp))
        Row(Modifier.align(Alignment.CenterHorizontally).focusRing(RoundedCornerShape(50)) { page = Page.CHECK }
                .glass(RoundedCornerShape(50), 0.9f).padding(horizontal = 16.dp, vertical = 9.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Filled.Warning, null, Modifier.size(16.dp), tint = Color(stateColor(VpnState.CONNECTING)))
            Spacer(Modifier.width(8.dp))
            Text("Найдено проблем: $problems", fontSize = 14.sp, color = GlassColors.Text)
        }
    }

    /** The server list on a glass card, with a small header. */
    @Composable
    private fun ServerCard(modifier: Modifier, emptyHint: String) {
        Glass(modifier = modifier) {
            Row(Modifier.fillMaxWidth().padding(start = 14.dp, end = 14.dp, top = 8.dp, bottom = 6.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text("Серверы", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = GlassColors.Text,
                     modifier = Modifier.weight(1f))
                if (servers.isNotEmpty()) Text("${servers.size}", fontSize = 13.sp, color = GlassColors.Faint)
            }
            if (servers.isEmpty()) {
                Text("Нет серверов.\n$emptyHint", Modifier.padding(14.dp), color = GlassColors.Dim, fontSize = 14.sp)
            }
            LazyColumn(contentPadding = PaddingValues(4.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                items(servers, key = { it.name }) { s -> ServerRow(s, s.name == selected, latency, true) }
            }
        }
    }

    @OptIn(ExperimentalLayoutApi::class)
    @Composable
    private fun TvScreen(st: VpnStatus, dark: Boolean) {
        var adding by remember { mutableIntStateOf(0) }    // 1 = QR for the phone, 2 = type it
        val shield = remember { FocusRequester() }
        val addButton = remember { FocusRequester() }
        Backdrop {
            // 5 % safe area: some TVs still overscan
            Row(Modifier.fillMaxSize().padding(horizontal = 48.dp, vertical = 27.dp)) {
                Column(Modifier.weight(1f).fillMaxHeight(), horizontalAlignment = Alignment.CenterHorizontally,
                       verticalArrangement = Arrangement.Center) {
                    Wordmark(30.sp)
                    Spacer(Modifier.height(30.dp))
                    GlassOrb(st.state, Modifier.focusRequester(shield).focusProperties { right = addButton }, 196.dp) {
                        toggle(st.state)
                    }
                    Spacer(Modifier.height(26.dp))
                    StatusBlock(st)
                    ProblemsChip()
                }
                Spacer(Modifier.width(40.dp))
                Column(Modifier.weight(1.15f).fillMaxHeight()) {
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        PillButton("Добавить", icon = Icons.Filled.Add, modifier = Modifier.focusRequester(addButton)) { adding = 1 }
                        PillButton("Обновить", icon = Icons.Filled.Refresh) { background { store.updateSubscriptions() } }
                        PillButton("Задержка", icon = Icons.Filled.PlayArrow) { testLatency() }
                        PillButton("Проверка сети", icon = Icons.Filled.CheckCircle) { page = Page.CHECK }
                        PillButton("Настройки", icon = Icons.Filled.Settings) { page = Page.SETTINGS }
                    }
                    Spacer(Modifier.height(18.dp))
                    if (busy) LinearProgressIndicator(Modifier.fillMaxWidth().padding(bottom = 8.dp), color = GlassColors.Accent)
                    ServerCard(Modifier.fillMaxWidth().weight(1f),
                               "Нажмите «Добавить» — подписку можно отправить с телефона по QR-коду")
                }
            }
        }
        InitialFocus(shield)
        when (adding) {
            1 -> AddFromPhoneDialog(dark, onDismiss = { adding = 0 }, onText = { adding = 0; add(it) },
                                    onManual = { adding = 2 })
            2 -> AddDialog(onDismiss = { adding = 0 }) { adding = 0; add(it) }
        }
    }

    @OptIn(ExperimentalLayoutApi::class)
    @Composable
    private fun ColumnScope.StatusBlock(st: VpnStatus) {
        Row(Modifier.align(Alignment.CenterHorizontally), verticalAlignment = Alignment.CenterVertically) {
            if (st.state != VpnState.OFF) {
                Box(Modifier.size(9.dp).background(Color(stateColor(st.state)), CircleShape))
                Spacer(Modifier.width(10.dp))
            }
            Text(STATE_TEXT[st.state]!!.replaceFirstChar { it.uppercase() }, fontSize = 21.sp,
                 fontWeight = FontWeight.SemiBold, color = GlassColors.Text)
        }
        if (st.state != VpnState.OFF && st.since != 0L) ConnectedFor(st.since)
        val note = when (st.state) {
            VpnState.ERROR -> st.message
            VpnState.BYPASS -> "Трафик идёт мимо VPN, пока сервер не ответит"
            VpnState.OFF -> if (servers.isEmpty()) "Добавьте подписку" else null
            else -> null
        }
        if (note != null) Text(note, fontSize = 13.sp, color = GlassColors.Dim,
                               textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                               modifier = Modifier.align(Alignment.CenterHorizontally).padding(top = 6.dp))
        Spacer(Modifier.height(12.dp))
        FlowRow(Modifier.align(Alignment.CenterHorizontally),
                horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
                verticalArrangement = Arrangement.spacedBy(8.dp)) {
            val name = (if (st.state == VpnState.OFF) selected else st.server)?.takeIf { it.isNotEmpty() }
            if (name != null) {
                val (flag, rest) = splitFlag(name)
                GlassChip(rest, leading = flag?.let { f -> { Text(f, fontSize = 14.sp) } })
            }
            if (st.state == VpnState.ON) {
                st.latency?.let { ms -> GlassChip("$ms мс", leading = { SignalBars(ms) }) }
                GlassChip("↓ ${humanRate(st.down)}   ↑ ${humanRate(st.up)}")
            }
        }
    }

    @Composable
    private fun CheckScreen(dark: Boolean) {
        androidx.activity.compose.BackHandler { page = Page.MAIN }
        val dim = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
        Backdrop {
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
                                    LinkButton(if (app.system) "Отключить" else "Удалить") { launchRemove(app) }
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
                                    Level.INFO -> VpnState.OFF
                                    Level.WARN -> VpnState.CONNECTING
                                    Level.BAD -> VpnState.ERROR
                                }))))
                                Spacer(Modifier.width(12.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(c.title, fontSize = 15.sp)
                                    Text(c.detail, color = dim, fontSize = 13.sp)
                                    if (c.fix != null && c.fixLabel != null) {
                                        LinkButton(c.fixLabel, Modifier.offset(x = (-10).dp)) { open(c.fix) }
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
                            LinkButton("Открыть настройки") { open(Intent(Settings.ACTION_SETTINGS)) }
                        }
                    }
                }
            }
        }
    }

    @Composable
    private fun ServerRow(s: Server, isSelected: Boolean, lat: Map<String, Int?>, dark: Boolean) {
        val shape = RoundedCornerShape(20.dp)
        Row(Modifier.fillMaxWidth().focusRing(shape, zoom = 1f) { select(s.name) }
                .then(if (isSelected) Modifier
                    .background(Brush.linearGradient(GlassColors.AccentGradient.map { it.copy(alpha = 0.16f) }), shape)
                    .border(1.dp, Brush.linearGradient(GlassColors.AccentGradient.map { it.copy(alpha = 0.7f) }), shape)
                else Modifier)
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically) {
            ServerBadge(s.name)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(splitFlag(s.name).second, maxLines = 1, overflow = TextOverflow.Ellipsis, fontSize = 16.sp,
                     color = GlassColors.Text, fontWeight = if (isSelected) FontWeight.SemiBold else FontWeight.Normal)
                Text(s.subtitle(), fontSize = 12.sp, color = GlassColors.Faint, maxLines = 1)
            }
            if (s.name in lat) {
                val ms = lat[s.name]
                Text(ms?.let { "$it мс" } ?: "—", fontSize = 13.sp, color = GlassColors.Dim,
                     style = androidx.compose.ui.text.TextStyle(fontFeatureSettings = "tnum"))
                Spacer(Modifier.width(8.dp))
                SignalBars(ms)
            }
            if (isSelected) {
                Spacer(Modifier.width(10.dp))
                Icon(Icons.Filled.CheckCircle, null, Modifier.size(20.dp), tint = GlassColors.Accent)
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
    Text(elapsed(now - since), fontSize = 44.sp, fontWeight = FontWeight.Thin, color = GlassColors.Text,
         style = androidx.compose.ui.text.TextStyle(fontFeatureSettings = "tnum"),   // digits don't jitter
         modifier = Modifier.align(Alignment.CenterHorizontally).padding(top = 2.dp))
}

internal fun elapsed(ms: Long): String {
    val t = (ms / 1000).coerceAtLeast(0)
    val d = t / 86400
    val hms = "%d:%02d:%02d".format(t / 3600 % 24, t / 60 % 60, t % 60)
    return if (d > 0) "$d д $hms" else hms
}


/** Round frosted icon button (phone top bar). */
@Composable
private fun RoundGlassButton(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, onClick: () -> Unit) {
    Box(Modifier.size(42.dp).focusRing(CircleShape, onClick = onClick).glass(CircleShape, 0.9f),
        contentAlignment = Alignment.Center) {
        Icon(icon, label, Modifier.size(20.dp), tint = GlassColors.Text)
    }
}
