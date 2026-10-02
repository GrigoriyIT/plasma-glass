package local.glassvpn

import android.app.PendingIntent
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService

/** Quick Settings tile: tap to connect / disconnect. */
class ToggleTile : TileService() {
    override fun onStartListening() = refresh()

    override fun onClick() {
        val on = GlassVpnService.status.value.state != VpnState.OFF
        if (on) {
            GlassVpnService.start(this, GlassVpnService.ACTION_DISCONNECT)
        } else if (VpnService.prepare(this) != null) {
            // the system's VPN consent dialog needs an activity
            val i = Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK).putExtra(MainActivity.EXTRA_CONNECT, true)
            if (Build.VERSION.SDK_INT >= 34) {
                startActivityAndCollapse(PendingIntent.getActivity(this, 0, i, PendingIntent.FLAG_IMMUTABLE))
            } else {
                @Suppress("DEPRECATION") startActivityAndCollapse(i)
            }
        } else {
            GlassVpnService.start(this)
        }
        refresh(!on)
    }

    private fun refresh(on: Boolean = GlassVpnService.status.value.state != VpnState.OFF) {
        val tile = qsTile ?: return
        tile.state = if (on) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
        tile.subtitle = GlassVpnService.status.value.server.takeIf { on && it.isNotEmpty() }
        tile.updateTile()
    }
}
