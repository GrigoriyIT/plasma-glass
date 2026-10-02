package local.glassvpn

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.InputStream
import java.net.Authenticator
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.PasswordAuthentication
import java.net.Proxy
import java.net.Socket
import java.net.URL

/** Servers, subscriptions and the selected server, in app-private storage. */
class Store(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("glassvpn", Context.MODE_PRIVATE)

    var subscriptions: List<String>
        get() = prefs.getString("subscriptions", "[]")!!.let { s -> JSONArray(s).let { a -> List(a.length()) { a.getString(it) } } }
        set(v) = prefs.edit().putString("subscriptions", JSONArray(v).toString()).apply()

    var servers: List<Server>
        get() = JSONArray(prefs.getString("servers", "[]")).let { a -> List(a.length()) { Server.fromJson(a.getJSONObject(it)) } }
        set(v) = prefs.edit().putString("servers", JSONArray(v.map { it.toJson() }).toString()).apply()

    var selected: String?
        get() = prefs.getString("selected", null)
        set(v) = prefs.edit().putString("selected", v).apply()

    /** Wanted on (survives the app being killed): the tile and always-on use it. */
    var wanted: Boolean
        get() = prefs.getBoolean("wanted", false)
        set(v) = prefs.edit().putBoolean("wanted", v).apply()

    /** Connect when the app is opened. */
    var autoConnect: Boolean
        get() = prefs.getBoolean("auto_connect", true)
        set(v) = prefs.edit().putBoolean("auto_connect", v).apply()

    /** Connect after the phone boots. */
    var bootStart: Boolean
        get() = prefs.getBoolean("boot_start", true)
        set(v) = prefs.edit().putBoolean("boot_start", v).apply()

    /** Server unreachable (e.g. mobile internet on a whitelist): let traffic go direct meanwhile. */
    var fallbackDirect: Boolean
        get() = prefs.getBoolean("fallback_direct", true)
        set(v) = prefs.edit().putBoolean("fallback_direct", v).apply()

    /** Packages that bypass the tunnel completely. */
    var excluded: Set<String>
        get() = prefs.getStringSet("excluded", emptySet())!!.toSet()
        set(v) = prefs.edit().putStringSet("excluded", v).apply()

    var latency: Map<String, Int?>
        get() = JSONObject(prefs.getString("latency", "{}")!!).let { o ->
            o.keys().asSequence().associateWith { if (o.isNull(it)) null else o.getInt(it) }
        }
        set(v) = prefs.edit().putString("latency", JSONObject().apply {
            v.forEach { (k, ms) -> put(k, ms ?: JSONObject.NULL) }
        }.toString()).apply()

    fun current(): Server? {
        val all = servers
        return all.firstOrNull { it.name == selected } ?: all.firstOrNull()
    }
}

/**
 * Text from the "add" dialog: subscription URLs and/or vless:// keys, one per line.
 * Keys become manual servers right away; returns true if there are URLs to fetch.
 */
fun Store.addInput(text: String): Boolean {
    val lines = text.lines().map { it.trim() }
    val manual = lines.mapNotNull { parseVless(it) }.map { it.copy(manual = true) }
    val urls = lines.filter { it.startsWith("https://") || it.startsWith("http://") }
    subscriptions = subscriptions + urls.filter { it !in subscriptions }
    if (manual.isNotEmpty()) {
        val names = manual.map { it.name }.toSet()
        servers = servers.filter { it.name !in names } + manual
    }
    return urls.isNotEmpty()
}

/** Re-fetch every subscription; keeps manual servers. Returns a message for the user. */
fun Store.updateSubscriptions(): String {
    val subs = subscriptions
    if (subs.isEmpty()) return "Подписок нет — добавьте ссылку"
    val fresh = mutableListOf<Server>()
    val errors = mutableListOf<String>()
    for (url in subs) {
        try {
            fresh += fetchSubscription(url, GlassVpnService.socks)
        } catch (e: Exception) {   // network, HTTP, decoding
            errors += e.message ?: e.javaClass.simpleName
        }
    }
    if (fresh.isEmpty()) return "Не удалось обновить подписки: " + errors.joinToString("; ").take(200)
    val names = fresh.map { it.name }.toSet()
    servers = fresh + servers.filter { it.manual && it.name !in names }
    return "Серверов: ${fresh.size}"
}

/** Fetch a subscription directly; if that fails and the tunnel is up, through it. */
fun fetchSubscription(url: String, socks: Socks?): List<Server> {
    fun get(proxy: Proxy): List<Server> {
        val c = URL(url).openConnection(proxy) as HttpURLConnection
        c.connectTimeout = 15000
        c.readTimeout = 20000
        c.setRequestProperty("User-Agent", "glassvpn/1.0")
        try {
            if (c.responseCode !in 200..299) throw java.io.IOException("HTTP ${c.responseCode}")
            return decodeSubscription(c.inputStream.use(InputStream::readBytes).toString(Charsets.UTF_8))
        } finally {
            c.disconnect()
        }
    }
    return try {
        get(Proxy.NO_PROXY)
    } catch (e: java.io.IOException) {
        if (socks == null) throw e
        Authenticator.setDefault(object : Authenticator() {
            override fun getPasswordAuthentication() = PasswordAuthentication(socks.user, socks.pass.toCharArray())
        })
        get(Proxy(Proxy.Type.SOCKS, InetSocketAddress("127.0.0.1", socks.port)))
    }
}

fun tcpLatency(host: String, port: Int, timeoutMs: Int = 3000): Int? {
    val t = System.nanoTime()
    return try {
        Socket().use { it.connect(InetSocketAddress(host, port), timeoutMs) }
        ((System.nanoTime() - t) / 1_000_000).toInt()
    } catch (e: Exception) {
        null
    }
}

/**
 * Fetch http://[host]/generate_204 through Xray's SOCKS5 (with auth); milliseconds or null.
 * A real request: Xray answers the SOCKS CONNECT before it has reached the server.
 */
fun socksProbe(socks: Socks, host: String = "connectivitycheck.gstatic.com", port: Int = 80,
               timeoutMs: Int = 6000): Int? {
    val t = System.nanoTime()
    return try {
        Socket().use { c ->
            c.connect(InetSocketAddress("127.0.0.1", socks.port), timeoutMs)
            c.soTimeout = timeoutMs
            val out = c.getOutputStream()
            val inp = c.getInputStream()
            fun read(n: Int) = ByteArray(n).also { b ->
                var off = 0
                while (off < n) { val r = inp.read(b, off, n - off); if (r < 0) throw java.io.EOFException(); off += r }
            }
            out.write(byteArrayOf(5, 1, 2)); out.flush()                 // username/password only
            if (!read(2).contentEquals(byteArrayOf(5, 2))) return null
            val u = socks.user.toByteArray(); val p = socks.pass.toByteArray()
            out.write(byteArrayOf(1, u.size.toByte()) + u + byteArrayOf(p.size.toByte()) + p); out.flush()
            if (read(2)[1] != 0.toByte()) return null
            val h = host.toByteArray()
            out.write(byteArrayOf(5, 1, 0, 3, h.size.toByte()) + h + byteArrayOf((port shr 8).toByte(), port.toByte()))
            out.flush()
            val reply = read(4)
            if (reply[1] != 0.toByte()) return null
            when (reply[3].toInt()) {                                     // bound address
                1 -> read(4 + 2)
                4 -> read(16 + 2)
                3 -> read((read(1)[0].toInt() and 255) + 2)
                else -> return null
            }
            out.write("GET /generate_204 HTTP/1.1\r\nHost: $host\r\nConnection: close\r\n\r\n".toByteArray())
            out.flush()
            val status = String(read(12), Charsets.US_ASCII)              // "HTTP/1.1 204"
            if (!status.startsWith("HTTP/")) return null
            ((System.nanoTime() - t) / 1_000_000).toInt()
        }
    } catch (e: Exception) {
        null
    }
}
