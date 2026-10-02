package local.glassvpn

import android.Manifest
import android.app.AppOpsManager
import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.os.Process
import android.provider.Settings

// An app can't uninstall others or change system network settings by itself: each
// check opens the system dialog or screen where the user makes the change.

/** INFO: shown with a button, but not a problem (e.g. something the system won't let us check). */
enum class Level { OK, INFO, WARN, BAD }

val Check.isProblem get() = level == Level.WARN || level == Level.BAD

data class Check(
    val title: String,
    val detail: String,
    val level: Level,
    val fixLabel: String? = null,
    val fix: Intent? = null,
)

data class VpnApp(val pkg: String, val label: String, val system: Boolean)

/**
 * Other apps with a VPN service. Matched by the BIND_VPN_SERVICE permission, not the intent:
 * many VPN apps don't export the service, and an intent query doesn't see those.
 */
fun otherVpnApps(ctx: Context): List<VpnApp> {
    val pm = ctx.packageManager
    return pm.getInstalledPackages(PackageManager.GET_SERVICES)
        .filter { p -> p.services?.any { it.permission == Manifest.permission.BIND_VPN_SERVICE } == true }
        .mapNotNull { it.applicationInfo }
        .filter { it.packageName != ctx.packageName }
        .distinctBy { it.packageName }
        .map { VpnApp(it.packageName, pm.getApplicationLabel(it).toString(),
                      it.flags and ApplicationInfo.FLAG_SYSTEM != 0) }
        .sortedBy { it.label.lowercase() }
}

/** System uninstall dialog; preinstalled apps can only be disabled on their settings page. */
fun removeIntent(app: VpnApp): Intent =
    if (app.system) Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${app.pkg}"))
    else Intent(Intent.ACTION_DELETE, Uri.parse("package:${app.pkg}"))

fun networkChecks(ctx: Context, vpnOn: Boolean): List<Check> {
    val cm = ctx.getSystemService(ConnectivityManager::class.java)
    @Suppress("DEPRECATION")
    val nets = cm.allNetworks.mapNotNull { n -> cm.getNetworkCapabilities(n)?.let { n to it } }
    val physical = nets.filter { (_, c) ->
        c.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN) &&
            c.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }
    val lp = physical.firstOrNull()?.first?.let { cm.getLinkProperties(it) }
    val out = mutableListOf<Check>()

    // internet itself
    out += when {
        physical.isEmpty() -> Check("Интернет", "Нет подключения к сети", Level.BAD,
                                    "Настройки сети", Intent(Settings.ACTION_WIRELESS_SETTINGS))
        physical.any { it.second.hasCapability(NetworkCapabilities.NET_CAPABILITY_CAPTIVE_PORTAL) } ->
            Check("Интернет", "Сеть требует входа (страница авторизации Wi-Fi)", Level.BAD,
                  "Открыть Wi-Fi", Intent(Settings.ACTION_WIFI_SETTINGS))
        physical.none { it.second.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) } ->
            Check("Интернет", "Сеть подключена, но интернет не отвечает", Level.WARN,
                  "Настройки сети", Intent(Settings.ACTION_WIRELESS_SETTINGS))
        else -> Check("Интернет", "Есть", Level.OK)
    }

    // someone else's tunnel is up
    val foreignVpn = !vpnOn && nets.any { it.second.hasTransport(NetworkCapabilities.TRANSPORT_VPN) }
    out += if (foreignVpn)
        Check("Другой VPN", "Сейчас работает VPN другого приложения. Если оно включено как «Постоянная VPN», " +
              "Glass VPN не сможет подключиться", Level.BAD, "Настройки VPN", Intent(Settings.ACTION_VPN_SETTINGS))
    else Check("Другой VPN", "Не активен", Level.OK)

    // Private DNS with a fixed server bypasses our DNS: routing falls back to IP addresses only
    val privateDns = lp?.privateDnsServerName
    out += if (privateDns != null)
        Check("Частный DNS", "Задан сервер $privateDns. Запросы идут мимо Glass VPN, и российские сайты на " +
              "зарубежных серверах пойдут через VPN. Стандартно: «Автоматически»", Level.WARN,
              "Настройки сети", Intent(Settings.ACTION_WIRELESS_SETTINGS))
    else Check("Частный DNS", "Автоматически или выключен", Level.OK)

    // a proxy left on the Wi-Fi by another VPN or a "speed-up" app
    val proxy = (cm.defaultProxy ?: lp?.httpProxy)?.takeIf { it.host != null || it.pacFileUrl != Uri.EMPTY }
    out += if (proxy != null)
        Check("Прокси", "Задан прокси ${proxy.host ?: proxy.pacFileUrl}:${proxy.port}. " +
              "Стандартно: «Нет». Если в Wi-Fi прокси нет, его оставило другое приложение — поможет сброс сети",
              Level.WARN, "Открыть Wi-Fi", Intent(Settings.ACTION_WIFI_SETTINGS))
    else Check("Прокси", "Нет", Level.OK)

    // background limits that kill or starve a VPN; a TV has no battery saver, Data Saver
    // or notification settings (their screens are empty stubs there)
    if (isTv(ctx)) return out
    val pkgUri = Uri.parse("package:${ctx.packageName}")
    out += backgroundChecks(ctx)

    out += if (cm.restrictBackgroundStatus == ConnectivityManager.RESTRICT_BACKGROUND_STATUS_ENABLED)
        Check("Экономия трафика", "Включена: фоновые соединения могут обрываться", Level.WARN,
              "Исключить Glass VPN", Intent(Settings.ACTION_IGNORE_BACKGROUND_DATA_RESTRICTIONS_SETTINGS, pkgUri))
    else Check("Экономия трафика", "Не мешает", Level.OK)

    if (android.os.Build.VERSION.SDK_INT >= 33 &&
        ctx.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
        out += Check("Уведомления", "Выключены: не видно состояния VPN", Level.WARN, "Включить",
                     Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                         .putExtra(Settings.EXTRA_APP_PACKAGE, ctx.packageName))
    }
    return out
}

/** Android has no public way to open "Reset network settings" directly: open Settings and say where. */
val RESET_HINT = "Система → Сброс настроек → «Сбросить настройки Wi-Fi, мобильного интернета и Bluetooth». " +
    "Удалятся сохранённые пароли Wi-Fi, пары Bluetooth и VPN-профили других приложений."

private val isXiaomi = Build.MANUFACTURER.equals("Xiaomi", ignoreCase = true) ||
    Build.BRAND.lowercase() in setOf("xiaomi", "redmi", "poco")

/**
 * MIUI/HyperOS "Autostart" (app op 10008). Without it Xiaomi won't let the VPN come up after a
 * reboot or be restarted after being killed. Null if the op can't be read.
 */
private fun miuiAutostart(ctx: Context): Boolean? = try {
    val ops = ctx.getSystemService(AppOpsManager::class.java)
    val check = AppOpsManager::class.java.getMethod("checkOpNoThrow", Int::class.java, Int::class.java, String::class.java)
    (check.invoke(ops, 10008, Process.myUid(), ctx.packageName) as Int) == AppOpsManager.MODE_ALLOWED
} catch (e: Exception) {
    null
}

/**
 * Background limits. Xiaomi swaps Android's battery-optimisation dialog for its own "Activity
 * control" page, whose "No restrictions" never reaches Android's list and can't be read by apps
 * (not even over adb) — so there it is a hint, not a warning, and Autostart is what gets checked.
 */
fun backgroundChecks(ctx: Context): List<Check> {
    val pkgUri = Uri.parse("package:${ctx.packageName}")
    val battery = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, pkgUri)
    val unrestricted = ctx.getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(ctx.packageName)
    if (!isXiaomi) {
        return listOf(if (unrestricted) Check("Работа в фоне", "Без ограничений", Level.OK)
                      else Check("Работа в фоне", "Android может останавливать VPN при экономии заряда",
                                 Level.WARN, "Разрешить", battery))
    }
    val autostartPage = Intent().setClassName("com.miui.securitycenter",
                                              "com.miui.permcenter.autostart.AutoStartManagementActivity")
    val autostart = when (miuiAutostart(ctx)) {
        true -> Check("Автозапуск", "Разрешён", Level.OK)
        false -> Check("Автозапуск", "Выключен: Xiaomi не даст VPN подняться после перезагрузки и " +
                       "перезапуститься после сбоя. Включите Glass VPN в списке", Level.WARN, "Включить", autostartPage)
        null -> Check("Автозапуск", "Xiaomi не даёт это проверить — включите Glass VPN в списке автозапуска",
                      Level.INFO, "Открыть", autostartPage)
    }
    val background = if (unrestricted) Check("Работа в фоне", "Без ограничений", Level.OK)
        else Check("Работа в фоне", "Xiaomi не даёт приложениям проверить эту настройку. " +
                   "В «Контроле активности» должно стоять «Нет ограничений»", Level.INFO, "Открыть", battery)
    return listOf(autostart, background)
}
