package local.glassvpn

import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.graphics.drawable.toBitmap
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
internal fun Backdrop(dark: Boolean, content: @Composable BoxScope.() -> Unit) {
    val bg = if (dark) listOf(Color(0xFF0E1726), Color(0xFF1B1530), Color(0xFF0B1F24))
             else listOf(Color(0xFFDDE8FF), Color(0xFFF3E6FF), Color(0xFFDDF6F0))
    Box(Modifier.fillMaxSize().background(Brush.linearGradient(bg)), content = content)
}

@Composable
internal fun TitleBar(title: String, onBack: () -> Unit, actions: @Composable RowScope.() -> Unit = {}) {
    Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад") }
        Text(title, fontSize = 22.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f),
             maxLines = 1, overflow = TextOverflow.Ellipsis)
        actions()
    }
}

@Composable
private fun SettingRow(title: String, detail: String, checked: Boolean? = null, action: String? = null,
                       onClick: () -> Unit) {
    val dim = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
    Row(Modifier.fillMaxWidth().clip14().clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, fontSize = 15.sp)
            Text(detail, fontSize = 13.sp, color = dim)
        }
        if (checked != null) Switch(checked = checked, onCheckedChange = { onClick() })
        if (action != null) Text(action, fontSize = 14.sp, color = MaterialTheme.colorScheme.primary,
                                 modifier = Modifier.padding(start = 8.dp))
    }
}

private fun Modifier.clip14() = clip(RoundedCornerShape(14.dp))

@Composable
internal fun SettingsScreen(dark: Boolean, store: Store, onBack: () -> Unit, onApps: () -> Unit,
                            open: (Intent) -> Unit) {
    BackHandler(onBack = onBack)
    val ctx = LocalContext.current
    var autoConnect by remember { mutableStateOf(store.autoConnect) }
    var bootStart by remember { mutableStateOf(store.bootStart) }
    // re-read when the screen comes back from a system dialog
    var resumed by remember { mutableIntStateOf(0) }
    val lifecycle = androidx.lifecycle.compose.LocalLifecycleOwner.current
    DisposableEffect(lifecycle) {
        val obs = androidx.lifecycle.LifecycleEventObserver { _, e ->
            if (e == androidx.lifecycle.Lifecycle.Event.ON_RESUME) resumed++
        }
        lifecycle.lifecycle.addObserver(obs)
        onDispose { lifecycle.lifecycle.removeObserver(obs) }
    }
    val unrestricted = remember(resumed) {
        ctx.getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(ctx.packageName)
    }
    val excludedCount = remember(resumed) { store.excluded.size }

    Backdrop(dark) {
        LazyColumn(Modifier.fillMaxSize().systemBarsPadding().padding(horizontal = 16.dp),
                   verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { TitleBar("Настройки", onBack) }
            item {
                Glass(dark, Modifier.fillMaxWidth()) {
                    SettingRow("Подключаться при запуске", "Открыли приложение — VPN включается сам",
                               checked = autoConnect) {
                        autoConnect = !autoConnect; store.autoConnect = autoConnect
                    }
                    SettingRow("Запускать при включении телефона", "VPN подключается после загрузки",
                               checked = bootStart) {
                        bootStart = !bootStart; store.bootStart = bootStart
                    }
                }
            }
            item {
                Glass(dark, Modifier.fillMaxWidth()) {
                    SettingRow("Приложения в обход VPN",
                               if (excludedCount == 0) "Все приложения идут через VPN"
                               else "Напрямую: $excludedCount", action = "Выбрать", onClick = onApps)
                }
            }
            item {
                Glass(dark, Modifier.fillMaxWidth().padding(bottom = 16.dp)) {
                    Text("Надёжная работа", fontWeight = FontWeight.Medium, fontSize = 16.sp,
                         modifier = Modifier.padding(start = 12.dp, top = 8.dp))
                    SettingRow("Работа в фоне",
                               if (unrestricted) "Без ограничений" else "Android может останавливать VPN при экономии заряда",
                               action = if (unrestricted) null else "Разрешить") {
                        if (!unrestricted) open(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                                                       Uri.parse("package:${ctx.packageName}")))
                    }
                    SettingRow("Постоянная VPN",
                               "Самый надёжный способ: система сама держит Glass VPN включённым и поднимает " +
                               "его после сбоев. Включите «Постоянная VPN» у Glass VPN в настройках VPN",
                               action = "Открыть") { open(Intent(Settings.ACTION_VPN_SETTINGS)) }
                }
            }
        }
    }
}

private data class AppEntry(val pkg: String, val label: String, val system: Boolean)

private fun loadApps(ctx: Context): List<AppEntry> {
    val pm = ctx.packageManager
    return pm.getInstalledApplications(0)
        .filter { it.packageName != ctx.packageName }
        .map { AppEntry(it.packageName, pm.getApplicationLabel(it).toString(),
                        // "system" = no launcher icon: services, providers, preinstalled plumbing
                        it.flags and ApplicationInfo.FLAG_SYSTEM != 0 && pm.getLaunchIntentForPackage(it.packageName) == null) }
}

/** Pick apps that bypass the tunnel. Returns through [onBack] whether the selection changed. */
@Composable
internal fun AppsScreen(dark: Boolean, store: Store, onBack: (changed: Boolean) -> Unit) {
    val ctx = LocalContext.current
    val initial = remember { store.excluded }
    var excluded by remember { mutableStateOf(initial) }
    var apps by remember { mutableStateOf<List<AppEntry>?>(null) }
    var query by remember { mutableStateOf("") }
    var showSystem by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { apps = withContext(Dispatchers.IO) { loadApps(ctx) } }
    val leave = { onBack(excluded != initial) }
    BackHandler(onBack = leave)
    val dim = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)

    Backdrop(dark) {
        Column(Modifier.fillMaxSize().systemBarsPadding().padding(horizontal = 16.dp)) {
            TitleBar("В обход VPN", leave)
            Text("Отмеченные приложения работают полностью напрямую, мимо туннеля (вместе с DNS). " +
                 "Если в настройках VPN включено «Блокировать подключения без VPN», у них не будет интернета.",
                 fontSize = 13.sp, color = dim, modifier = Modifier.padding(vertical = 6.dp))
            OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), singleLine = true,
                              placeholder = { Text("Поиск") })
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 4.dp)) {
                Row(Modifier.clip14().clickable { showSystem = !showSystem }.padding(end = 12.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(showSystem, null)
                    Text("Показать системные", fontSize = 14.sp)
                }
                Spacer(Modifier.weight(1f))
                if (excluded.isNotEmpty()) TextButton(onClick = { excluded = emptySet(); store.excluded = excluded }) {
                    Text("Сбросить (${excluded.size})")
                }
            }
            Glass(dark, Modifier.fillMaxWidth().weight(1f).padding(bottom = 16.dp)) {
                val list = apps
                if (list == null) {
                    LinearProgressIndicator(Modifier.fillMaxWidth().padding(16.dp))
                } else {
                    val q = query.trim().lowercase()
                    val shown = list.filter { (showSystem || !it.system || it.pkg in excluded) &&
                                              (q.isEmpty() || q in it.label.lowercase() || q in it.pkg) }
                        // selected first, the order fixed when the screen opened so rows don't jump
                        .sortedWith(compareBy<AppEntry>({ it.pkg !in initial }, { it.label.lowercase() }))
                    LazyColumn {
                        items(shown, key = { it.pkg }) { app ->
                            val on = app.pkg in excluded
                            Row(Modifier.fillMaxWidth().clip14().clickable {
                                    excluded = if (on) excluded - app.pkg else excluded + app.pkg
                                    store.excluded = excluded
                                }.padding(horizontal = 10.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically) {
                                AppIcon(app.pkg)
                                Spacer(Modifier.width(12.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(app.label, fontSize = 15.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text(app.pkg, fontSize = 11.sp, color = dim, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                }
                                Checkbox(on, null)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AppIcon(pkg: String) {
    val ctx = LocalContext.current
    val icon by produceState<ImageBitmap?>(null, pkg) {
        value = withContext(Dispatchers.IO) {
            try { ctx.packageManager.getApplicationIcon(pkg).toBitmap(96, 96).asImageBitmap() } catch (e: Exception) { null }
        }
    }
    Box(Modifier.size(36.dp)) { icon?.let { Image(it, null, Modifier.fillMaxSize()) } }
}
