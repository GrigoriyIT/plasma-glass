package local.glassvpn

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.VpnService

/** Connect after boot (if enabled) and after an app update (if the tunnel was on). */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val store = Store(context)
        val go = when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED -> store.bootStart
            Intent.ACTION_MY_PACKAGE_REPLACED -> store.wanted
            else -> false
        }
        // without the user's VPN consent there is nothing we can start from the background
        if (go && store.servers.isNotEmpty() && VpnService.prepare(context) == null) {
            GlassVpnService.start(context, ifDown = true)
        }
    }
}
