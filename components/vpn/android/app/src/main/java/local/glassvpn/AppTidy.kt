package local.glassvpn

import android.app.ActivityManager
import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.os.Process
import android.provider.Settings
import android.util.Log

/**
 * A TV with little memory (Xiaomi Mi TV: 1.8 GB): video apps stay cached after the user goes
 * back to the home screen, and the system then swaps the launcher itself out. So user-installed
 * apps are closed a few minutes after they leave the screen, and all of them in standby.
 * killBackgroundProcesses() spares the app on screen and anything playing in the background
 * (a foreground service). Opt-in: needs usage access, which a TV grants only over adb:
 *   adb shell appops set local.glassvpn GET_USAGE_STATS allow
 */
class AppTidy(private val ctx: Context) {
    companion object {
        private const val TAG = "GlassVPN"
        const val AFTER_MS = 5 * 60_000L
        private const val LOOKBACK_MS = 6 * 3600_000L
    }

    private val am = ctx.getSystemService(ActivityManager::class.java)
    private val usm = ctx.getSystemService(UsageStatsManager::class.java)
    private val closed = HashMap<String, Long>()   // package -> its background event already handled

    @Suppress("DEPRECATION")
    fun allowed(): Boolean = ctx.getSystemService(AppOpsManager::class.java).checkOpNoThrow(
        AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), ctx.packageName) == AppOpsManager.MODE_ALLOWED

    /** User-installed apps, except this one, the home screen and the keyboard. */
    private fun candidates(): Set<String> {
        val pm = ctx.packageManager
        val home = pm.resolveActivity(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME), 0)
            ?.activityInfo?.packageName
        val ime = Settings.Secure.getString(ctx.contentResolver, Settings.Secure.DEFAULT_INPUT_METHOD)
            ?.substringBefore('/')
        return pm.getInstalledApplications(0)
            .filter { it.flags and ApplicationInfo.FLAG_SYSTEM == 0 }
            .map { it.packageName }
            .filter { it != ctx.packageName && it != home && it != ime }
            .toSet()
    }

    /** Close apps that left the screen [AFTER_MS] ago; with [all] (standby), every app not on screen. */
    @Suppress("DEPRECATION")
    fun run(all: Boolean) {
        if (!allowed()) return
        val now = System.currentTimeMillis()
        val apps = candidates()
        val last = HashMap<String, Pair<Int, Long>>()   // package -> (event type, time)
        val events = usm.queryEvents(now - LOOKBACK_MS, now)
        val e = UsageEvents.Event()
        while (events.hasNextEvent()) {
            events.getNextEvent(e)
            if (e.packageName in apps && (e.eventType == UsageEvents.Event.MOVE_TO_FOREGROUND ||
                                          e.eventType == UsageEvents.Event.MOVE_TO_BACKGROUND)) {
                last[e.packageName] = e.eventType to e.timeStamp
            }
        }
        for (pkg in apps) {
            val (type, at) = last[pkg] ?: (UsageEvents.Event.MOVE_TO_BACKGROUND to 0L)
            if (type == UsageEvents.Event.MOVE_TO_FOREGROUND) continue   // on screen
            // at == 0: off screen since before the look-back, i.e. long ago
            if (!all && at != 0L && now - at < AFTER_MS) continue
            // closed once already; in standby apps with no recent use are closed again
            // (some restart themselves in the background)
            if (closed[pkg] == at && !(all && at == 0L)) continue
            am.killBackgroundProcesses(pkg)
            closed[pkg] = at
            Log.i(TAG, "closed $pkg: " + if (at != 0L) "off screen for ${(now - at) / 60_000} min" else "not used lately")
        }
    }
}
