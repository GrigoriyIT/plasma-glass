package local.glassvpn

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.Network
import android.net.NetworkCapabilities
import android.net.VpnService
import android.os.ParcelFileDescriptor
import android.os.PowerManager
import android.service.quicksettings.TileService
import android.util.Log
import hev.htproxy.TProxyService
import kotlinx.coroutines.flow.MutableStateFlow
import libv2ray.CoreCallbackHandler
import libv2ray.CoreController
import libv2ray.Libv2ray
import java.io.File
import java.net.Inet4Address
import java.net.InetAddress
import java.net.ServerSocket
import java.security.SecureRandom
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

enum class VpnState { OFF, CONNECTING, ON, ERROR }

data class VpnStatus(
    val state: VpnState = VpnState.OFF,
    val server: String = "",
    val latency: Int? = null,
    val down: Long = 0,      // bytes per second
    val up: Long = 0,
    val message: String? = null,
    val since: Long = 0,     // wall-clock ms of the first successful check of this connection
)

val STATE_TEXT = mapOf(VpnState.OFF to "отключено", VpnState.CONNECTING to "подключение…",
                       VpnState.ON to "подключено", VpnState.ERROR to "сервер не отвечает")

fun humanRate(bps: Long): String = when {
    bps >= 1 shl 20 -> "%.1f МБ/с".format(bps / 1048576.0)
    bps >= 1 shl 10 -> "${bps shr 10} КБ/с"
    else -> "$bps Б/с"
}

/**
 * TUN (VpnService) -> hev-socks5-tunnel -> Xray SOCKS5 on localhost -> VLESS.
 * The app itself is excluded from the VPN, so Xray's own traffic goes out directly.
 */
class GlassVpnService : VpnService() {
    companion object {
        const val ACTION_CONNECT = "local.glassvpn.CONNECT"
        const val ACTION_DISCONNECT = "local.glassvpn.DISCONNECT"
        /** Boot / update / always-on: connect, but leave a working tunnel alone. */
        const val EXTRA_IF_DOWN = "if_down"
        private const val TAG = "GlassVPN"
        private const val CHANNEL = "vpn"
        private const val NOTIFY_ID = 1
        private const val WATCHDOG_MIN = 30_000_000_000L    // ns
        private const val WATCHDOG_MAX = 300_000_000_000L
        private const val FALLBACK_DNS = "77.88.8.8"   // Yandex: answers for Russian names

        val status = MutableStateFlow(VpnStatus())
        /** Current SOCKS credentials, for fetching subscriptions through the tunnel. */
        @Volatile var socks: Socks? = null
            private set
        private var coreEnvReady = false

        fun start(ctx: Context, action: String = ACTION_CONNECT, ifDown: Boolean = false) {
            val i = Intent(ctx, GlassVpnService::class.java).setAction(action).putExtra(EXTRA_IF_DOWN, ifDown)
            if (action == ACTION_CONNECT) ctx.startForegroundService(i) else ctx.startService(i)
        }
    }

    private val worker = Executors.newSingleThreadExecutor()
    private val timer = Executors.newSingleThreadScheduledExecutor()
    private var ticker: ScheduledFuture<*>? = null
    private var tun: ParcelFileDescriptor? = null
    private var core: CoreController? = null
    @Volatile private var running = false
    private var server: Server? = null
    private var serverIp: String? = null
    private var localDns: List<String> = emptyList()
    @Volatile private var underlying: Network? = null
    private var lastStats: LongArray? = null
    private var lastStatsAt = 0L
    private var failures = 0
    private var errorSince = 0L                    // nanoTime when the server stopped answering
    private var restartDelay = WATCHDOG_MIN
    private var tick = 0

    private val cm by lazy { getSystemService(ConnectivityManager::class.java) }
    private val netCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) { onNetwork(network) }
        override fun onLinkPropertiesChanged(network: Network, lp: LinkProperties) { onNetwork(network) }
        override fun onLost(network: Network) {
            if (network == underlying) { underlying = null; setUnderlyingNetworks(null) }
        }
    }

    override fun onCreate() {
        super.onCreate()
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, "VPN", NotificationManager.IMPORTANCE_LOW).apply { setShowBadge(false) })
        // the app is outside its own VPN, so this follows the physical network
        cm.registerDefaultNetworkCallback(netCallback)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_DISCONNECT) {
            worker.execute { disconnect() }
            return START_NOT_STICKY
        }
        // a sticky restart after the system killed us: only if the user still wants the tunnel
        if (intent == null && !Store(this).wanted) {
            stopSelf()
            return START_NOT_STICKY
        }
        // ACTION_CONNECT, always-on (android.net.VpnService) or a sticky restart
        val st = status.value.takeIf { it.state != VpnState.OFF } ?: VpnStatus(VpnState.CONNECTING)
        startForeground(NOTIFY_ID, notification(st), ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        val ifDown = intent == null || intent.action != ACTION_CONNECT || intent.getBooleanExtra(EXTRA_IF_DOWN, false)
        worker.execute { if (!(ifDown && running)) connect() }
        return START_STICKY
    }

    override fun onRevoke() {   // another VPN took over, or the user revoked us
        worker.execute { disconnect() }
    }

    override fun onDestroy() {
        cm.unregisterNetworkCallback(netCallback)
        worker.execute { teardown() }
        worker.shutdown()
        worker.awaitTermination(3, TimeUnit.SECONDS)
        timer.shutdownNow()
        publish(VpnStatus())
        super.onDestroy()
    }

    // ------------------------------------------------------------- lifecycle --

    private fun connect() {
        val store = Store(this)
        store.wanted = true
        teardown()
        val s = store.current() ?: return fail("Нет серверов: добавьте подписку")
        server = s
        publish(VpnStatus(VpnState.CONNECTING, s.name))
        serverIp = resolveIpv4(s.host) ?: return fail("Не удалось найти адрес сервера ${s.host}")
        val creds = Socks(freePort(), randomToken(), randomToken())
        socks = creds
        if (underlying == null) underlying = physical(cm.activeNetwork)   // before the callback's first event
        localDns = dnsOf(underlying)
        try {
            if (!coreEnvReady) {
                copyGeoData()
                Libv2ray.initCoreEnv(filesDir.absolutePath, "")
                coreEnvReady = true
            }
            core = Libv2ray.newCoreController(CoreCallbacks()).also {
                it.startLoop(xrayConfig(s, serverIp, creds, localDns), 0)
            }
        } catch (e: Exception) {
            Log.e(TAG, "xray", e)
            return fail("Xray: ${e.message}")
        }

        val builder = Builder()
            .setSession(s.name)
            .setMtu(TUN_MTU)
            .addAddress(TUN_ADDR, 30)
            .addDnsServer(TUN_DNS)
            .setMetered(false)
            .setConfigureIntent(PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
                                                          PendingIntent.FLAG_IMMUTABLE))
            .addDisallowedApplication(packageName)
        // apps the user sent around the tunnel: the system routes them (and their DNS) directly
        for (pkg in store.excluded) {
            try { builder.addDisallowedApplication(pkg) } catch (e: Exception) { /* uninstalled */ }
        }
        // no IPv6 address or route: Android then blocks IPv6 for VPN'd apps instead of leaking it
        for ((addr, len) in routesExcluding(EXCLUDED_NETS)) builder.addRoute(addr, len)
        underlying?.let { builder.setUnderlyingNetworks(arrayOf(it)) }
        tun = try {
            builder.establish()
        } catch (e: Exception) {
            Log.e(TAG, "establish", e)
            null
        } ?: return fail("Нет разрешения на VPN")

        val conf = File(filesDir, "hev.yaml")
        conf.writeText(hevConfig(creds))      // app-private; holds the SOCKS password
        if (!TProxyService.TProxyStartService(conf.absolutePath, tun!!.fd)) return fail("Не запустился TUN")

        running = true
        failures = 0
        errorSince = 0L
        restartDelay = WATCHDOG_MIN
        lastStats = null
        ticker = timer.scheduleWithFixedDelay({ tick() }, 0, 2, TimeUnit.SECONDS)
        TileService.requestListeningState(this, android.content.ComponentName(this, ToggleTile::class.java))
    }

    private fun disconnect() {
        Store(this).wanted = false
        teardown()
        publish(VpnStatus())
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
        TileService.requestListeningState(this, android.content.ComponentName(this, ToggleTile::class.java))
    }

    private fun teardown() {
        running = false
        ticker?.cancel(false)
        ticker = null
        if (TProxyService.TProxyIsRunning()) TProxyService.TProxyStopService()
        try { core?.stopLoop() } catch (e: Exception) { Log.w(TAG, "stopLoop", e) }
        core = null
        try { tun?.close() } catch (e: Exception) { }
        tun = null
        socks = null
    }

    private fun fail(message: String) {
        Log.w(TAG, message)
        teardown()
        publish(VpnStatus(VpnState.ERROR, server?.name ?: "", message = message))
        // keep the notification so the error is visible; the user can retry or disconnect
    }

    /** New physical network: follow it, and restart Xray if the local DNS changed. */
    private fun onNetwork(reported: Network) {
        // the default-network callback reports our own VPN too: look past it
        val network = physical(reported) ?: return
        underlying = network
        if (!running) return
        setUnderlyingNetworks(arrayOf(network))
        worker.execute {
            val dns = dnsOf(network)
            if (running && dns != localDns) {
                Log.i(TAG, "network DNS $localDns -> $dns, restarting Xray")
                localDns = dns
                restartCore()
            }
        }
    }

    /** Restart Xray inside the running tunnel (TUN and hev stay up; the server is re-resolved). */
    private fun restartCore() {
        val s = server ?: return
        val creds = socks ?: return
        resolveIpv4(s.host)?.let { serverIp = it }
        try {
            core?.stopLoop()
            core?.startLoop(xrayConfig(s, serverIp, creds, localDns), 0)
        } catch (e: Exception) {
            Log.e(TAG, "xray restart", e)
        }
    }

    // ------------------------------------------------------- status & probe --

    private fun tick() {
        if (!running) return
        val interactive = getSystemService(PowerManager::class.java).isInteractive
        val now = System.nanoTime()
        // [tx packets, tx bytes, rx packets, rx bytes]; tx = towards the apps
        val stats = TProxyService.TProxyGetStats()
        var down = 0L
        var up = 0L
        val prev = lastStats
        if (prev != null && stats != null) {
            val dt = (now - lastStatsAt) / 1e9
            down = ((stats[1] - prev[1]) / dt).toLong()
            up = ((stats[3] - prev[3]) / dt).toLong()
        }
        lastStats = stats
        lastStatsAt = now
        val cur = status.value
        var next = cur.copy(down = down, up = up)
        // live check every 4 s, only while the screen is on (keeps the radio idle otherwise)
        // (every tick while connecting or failing, so a dead server shows up quickly)
        // (every tick while connecting or failing so a dead server shows up quickly; every 30 s
        // when failing with the screen off)
        val n = tick++
        val failing = cur.state != VpnState.ON || failures > 0
        if ((n % 2 == 0 && interactive) || (failing && (interactive || n % 15 == 0))) {
            val ms = socks?.let { socksProbe(it) }
            if (!running) return
            if (ms != null) {
                failures = 0
                errorSince = 0L
                restartDelay = WATCHDOG_MIN
                next = next.copy(state = VpnState.ON, latency = ms, message = null,
                                 since = cur.since.takeIf { it != 0L } ?: System.currentTimeMillis())
            } else if (++failures >= 3) {
                next = next.copy(state = VpnState.ERROR, latency = null)
                if (errorSince == 0L) errorSince = now
            }
        }
        publish(next)
        // watchdog: Xray died, or the server has been silent too long -> restart it, backing off
        val coreDead = core?.isRunning == false
        if (coreDead || (errorSince != 0L && now - errorSince > restartDelay)) {
            Log.w(TAG, if (coreDead) "watchdog: Xray stopped" else "watchdog: no answer for ${restartDelay / 1_000_000_000} s")
            errorSince = if (errorSince != 0L) now else 0L
            restartDelay = minOf(restartDelay * 2, WATCHDOG_MAX)
            worker.execute { if (running) restartCore() }
        }
    }

    private fun publish(st: VpnStatus) {
        status.value = st
        if (st.state != VpnState.OFF) {
            getSystemService(NotificationManager::class.java).notify(NOTIFY_ID, notification(st))
        }
    }

    private fun notification(st: VpnStatus): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
                                             PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, GlassVpnService::class.java)
            .setAction(ACTION_DISCONNECT), PendingIntent.FLAG_IMMUTABLE)
        val text = when (st.state) {
            VpnState.ON -> "↓ ${humanRate(st.down)}  ↑ ${humanRate(st.up)}" + (st.latency?.let { "  ·  $it мс" } ?: "")
            VpnState.ERROR -> st.message ?: STATE_TEXT[st.state]
            else -> STATE_TEXT[st.state]
        }
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_shield)
            .setContentTitle(if (st.server.isNotEmpty()) "Glass VPN · ${st.server}" else "Glass VPN")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setColor(stateColor(st.state).toInt())
            .apply {   // the system ticks the "connected for" time itself
                if (st.since != 0L) setWhen(st.since).setShowWhen(true).setUsesChronometer(true)
                else setShowWhen(false)
            }
            .addAction(Notification.Action.Builder(null, "Отключить", stop).build())
            .setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE)
            .build()
    }

    // --------------------------------------------------------------- helpers --

    private fun isPhysical(n: Network) = cm.getNetworkCapabilities(n)?.let {
        it.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN) &&
            it.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    } == true

    /** [n] if it is a physical network, else any physical network with internet. */
    @Suppress("DEPRECATION")
    private fun physical(n: Network?): Network? =
        n?.takeIf { isPhysical(it) } ?: cm.allNetworks.firstOrNull { isPhysical(it) }

    private fun dnsOf(network: Network?): List<String> {
        val lp = network?.let { cm.getLinkProperties(it) }
        val v4 = lp?.dnsServers?.filterIsInstance<Inet4Address>()?.mapNotNull { it.hostAddress }.orEmpty()
        return v4.ifEmpty { listOf(FALLBACK_DNS) }
    }

    private fun resolveIpv4(host: String): String? = try {
        InetAddress.getAllByName(host).firstOrNull { it is Inet4Address }?.hostAddress
    } catch (e: Exception) {
        null
    }

    /** Xray's geodata loader stats real files, so the .dat files from the APK go to filesDir (once per version). */
    private fun copyGeoData() {
        val version = packageManager.getPackageInfo(packageName, 0).lastUpdateTime.toString()
        val stamp = File(filesDir, "geo.version")
        if (stamp.exists() && stamp.readText() == version) return
        for (name in listOf("geoip.dat", "geosite.dat")) {
            val tmp = File(filesDir, "$name.tmp")
            assets.open(name).use { input -> tmp.outputStream().use { input.copyTo(it) } }
            tmp.renameTo(File(filesDir, name))
        }
        stamp.writeText(version)
    }

    private fun freePort(): Int = ServerSocket(0).use { it.localPort }

    private fun randomToken(): String {
        val b = ByteArray(12).also { SecureRandom().nextBytes(it) }
        return b.joinToString("") { "%02x".format(it) }
    }

    private inner class CoreCallbacks : CoreCallbackHandler {
        override fun startup(): Long = 0
        override fun shutdown(): Long = 0
        override fun onEmitStatus(p0: Long, p1: String?): Long {
            Log.i(TAG, "xray: $p1")
            return 0
        }
    }
}

fun stateColor(s: VpnState): Long = when (s) {
    VpnState.CONNECTING -> 0xFFF5B83D
    VpnState.ON -> 0xFF34C759
    VpnState.ERROR -> 0xFFFF453A
    VpnState.OFF -> 0xFF8E8E93
}
