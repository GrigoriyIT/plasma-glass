package local.glassvpn

import org.json.JSONArray
import org.json.JSONObject
import java.net.URLDecoder
import java.util.Base64

// Same parsing and routing as components/vpn/glassvpn.py, for Xray + hev-socks5-tunnel.

data class Server(
    val name: String,
    val uuid: String,
    val host: String,
    val port: Int,
    val type: String = "tcp",
    val security: String = "none",
    val sni: String = "",
    val fp: String = "",
    val pbk: String = "",
    val sid: String = "",
    val flow: String = "",
    val path: String = "",
    val hostHeader: String = "",
    val serviceName: String = "",
    val alpn: String = "",
    val encryption: String = "none",
    val mode: String = "",
    val spx: String = "",
    val manual: Boolean = false,     // added by hand: kept when subscriptions update
) {
    fun toJson(): JSONObject = JSONObject()
        .put("name", name).put("uuid", uuid).put("host", host).put("port", port)
        .put("type", type).put("security", security).put("sni", sni).put("fp", fp)
        .put("pbk", pbk).put("sid", sid).put("flow", flow).put("path", path)
        .put("host_header", hostHeader).put("service_name", serviceName).put("alpn", alpn)
        .put("encryption", encryption).put("mode", mode).put("spx", spx).put("manual", manual)

    companion object {
        fun fromJson(o: JSONObject) = Server(
            name = o.optString("name"), uuid = o.optString("uuid"), host = o.optString("host"),
            port = o.optInt("port", 443), type = o.optString("type", "tcp"),
            security = o.optString("security", "none"), sni = o.optString("sni"), fp = o.optString("fp"),
            pbk = o.optString("pbk"), sid = o.optString("sid"), flow = o.optString("flow"),
            path = o.optString("path"), hostHeader = o.optString("host_header"),
            serviceName = o.optString("service_name"), alpn = o.optString("alpn"),
            encryption = o.optString("encryption", "none"), mode = o.optString("mode"), spx = o.optString("spx"),
            manual = o.optBoolean("manual"),
        )
    }
}

private fun unquote(s: String): String =
    try { URLDecoder.decode(s.replace("+", "%2B"), "UTF-8") } catch (e: IllegalArgumentException) { s }

/** vless://uuid@host:port?params#name -> Server, or null. */
fun parseVless(uri: String): Server? {
    var rest = uri.trim()
    if (!rest.startsWith("vless://", ignoreCase = true)) return null
    rest = rest.substring(8)
    var fragment = ""
    rest.indexOf('#').takeIf { it >= 0 }?.let { fragment = rest.substring(it + 1); rest = rest.substring(0, it) }
    var query = ""
    rest.indexOf('?').takeIf { it >= 0 }?.let { query = rest.substring(it + 1); rest = rest.substring(0, it) }
    rest = rest.trimEnd('/')
    val at = rest.lastIndexOf('@')
    if (at <= 0) return null
    val user = unquote(rest.substring(0, at))
    val hostPort = rest.substring(at + 1)
    val host: String
    val portStr: String
    if (hostPort.startsWith("[")) {          // [ipv6]:port
        val end = hostPort.indexOf(']')
        if (end < 0) return null
        host = hostPort.substring(1, end)
        portStr = hostPort.substring(end + 1).removePrefix(":")
    } else {
        val colon = hostPort.lastIndexOf(':')
        host = if (colon >= 0) hostPort.substring(0, colon) else hostPort
        portStr = if (colon >= 0) hostPort.substring(colon + 1) else ""
    }
    if (host.isEmpty() || user.isEmpty()) return null
    val port = if (portStr.isEmpty()) 443 else portStr.toIntOrNull()?.takeIf { it in 1..65535 } ?: return null
    val q = query.split('&').filter { it.isNotEmpty() }.associate {
        val eq = it.indexOf('=')
        if (eq < 0) unquote(it) to "" else unquote(it.substring(0, eq)) to unquote(it.substring(eq + 1))
    }
    fun p(k: String, d: String = "") = q[k]?.takeIf { it.isNotEmpty() } ?: d
    return Server(
        name = unquote(fragment).ifEmpty { "$host:$port" },
        uuid = user, host = host, port = port,
        type = p("type", "tcp"), security = p("security", "none"),
        sni = p("sni").ifEmpty { p("host") }, fp = p("fp"), pbk = p("pbk"), sid = p("sid"),
        flow = p("flow"), path = p("path"), hostHeader = p("host"), serviceName = p("serviceName"),
        alpn = p("alpn"), encryption = p("encryption", "none"), mode = p("mode"), spx = p("spx"),
    )
}

/** Plain or base64 list of vless:// links. */
fun decodeSubscription(body: String): List<Server> {
    var text = body.trim()
    if ("://" !in text) {  // most subscriptions are base64 of a newline-separated list
        val compact = text.filterNot { it.isWhitespace() }
        val padded = compact + "=".repeat((4 - compact.length % 4) % 4)
        text = try {
            val dec = if ('-' in compact || '_' in compact) Base64.getUrlDecoder() else Base64.getDecoder()
            String(dec.decode(padded), Charsets.UTF_8)
        } catch (e: IllegalArgumentException) {
            text
        }
    }
    return text.lines().mapNotNull { parseVless(it) }
}

// ---------------------------------------------------------------- configs --

const val TUN_ADDR = "198.18.0.1"
const val TUN_DNS = "198.18.0.2"          // answered by hev's mapped DNS
const val MAPPED_NET = "198.19.0.0"       // fake IPs, turned back into names before SOCKS
const val TUN_MTU = 8500

val RU_SUFFIXES = listOf("ru", "su", "xn--p1ai", "xn--p1acf", "xn--d1acj3b")  // .рф .рус .дети

// stay outside the tunnel: LAN, link-local, carrier NAT, multicast
val EXCLUDED_NETS = listOf("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
                           "100.64.0.0/10", "224.0.0.0/3")

/** Local SOCKS5 for hev, and a second port that always goes to the server (the live check). */
data class Socks(val port: Int, val user: String, val pass: String, val probePort: Int = 0) {
    val probe get() = copy(port = probePort)
}

private fun obj(vararg pairs: Pair<String, Any?>) = JSONObject().apply {
    for ((k, v) in pairs) if (v != null) put(k, v)
}
private fun arr(vararg items: Any) = JSONArray(items.toList())
private fun arr(items: List<Any>) = JSONArray(items)

fun streamSettings(s: Server): JSONObject {
    val net = mapOf("tcp" to "tcp", "raw" to "tcp", "grpc" to "grpc", "ws" to "ws",
                    "httpupgrade" to "httpupgrade", "xhttp" to "xhttp", "splithttp" to "xhttp",
                    "http" to "xhttp", "h2" to "xhttp")[s.type] ?: "tcp"
    val security = if (s.security == "tls" || s.security == "reality") s.security else "none"
    val st = obj("network" to net, "security" to security)
    when (security) {
        "tls" -> st.put("tlsSettings", obj(
            "serverName" to s.sni.ifEmpty { s.host }, "fingerprint" to s.fp.ifEmpty { "chrome" },
            "alpn" to s.alpn.takeIf { it.isNotEmpty() }?.let { arr(it.split(",")) }))
        "reality" -> st.put("realitySettings", obj(
            "serverName" to s.sni, "fingerprint" to s.fp.ifEmpty { "chrome" },
            "publicKey" to s.pbk, "shortId" to s.sid, "spiderX" to s.spx))
    }
    when (net) {
        "grpc" -> st.put("grpcSettings", obj("serviceName" to s.serviceName))
        "ws" -> st.put("wsSettings", obj("path" to s.path.ifEmpty { "/" },
            "headers" to s.hostHeader.takeIf { it.isNotEmpty() }?.let { obj("Host" to it) }))
        "httpupgrade" -> st.put("httpupgradeSettings", obj("path" to s.path.ifEmpty { "/" }, "host" to s.hostHeader))
        "xhttp" -> st.put("xhttpSettings", obj("path" to s.path.ifEmpty { "/" }, "host" to s.hostHeader,
                                               "mode" to s.mode.ifEmpty { "auto" }))
    }
    return st
}

/**
 * Xray: password-protected SOCKS5 on localhost (Russian apps scan for open local
 * proxies) -> VLESS; Russian and local destinations go direct.
 * [serverIp] is resolved by the app beforehand, [localDns] is the physical network's
 * resolver: Go has no system resolver on Android.
 */
fun xrayConfig(s: Server, serverIp: String?, socks: Socks, localDns: List<String>, bypass: Boolean = false): String {
    val user = obj("id" to s.uuid, "encryption" to s.encryption.ifEmpty { "none" },
                   "flow" to s.flow.takeIf { it.isNotEmpty() })
    val ruDomains = RU_SUFFIXES.map { "domain:$it" } + "geosite:category-ru"
    val dnsServers = JSONArray()
    for (ip in localDns) dnsServers.put(obj("address" to ip, "port" to 53,
                                            "domains" to arr(ruDomains), "skipFallback" to true))
    dnsServers.put("https://1.1.1.1/dns-query")   // through the proxy
    // when DoH can't get through (server down, mobile whitelist) the network's own DNS answers
    for (ip in localDns) dnsServers.put(obj("address" to ip, "port" to 53))
    val rules = JSONArray()
        // the live check always goes to the server, even while traffic bypasses it
        .put(obj("type" to "field", "inboundTag" to arr("probe"), "outboundTag" to "proxy"))
        // probes of our own TUN addresses (e.g. Private DNS on 198.18.0.2:853) fail fast
        .put(obj("type" to "field", "ip" to arr("198.18.0.0/15"), "outboundTag" to "block"))
    if (localDns.isNotEmpty()) rules.put(obj("type" to "field", "ip" to arr(localDns), "outboundTag" to "direct"))
    rules.put(obj("type" to "field", "domain" to arr(ruDomains), "outboundTag" to "direct"))
        .put(obj("type" to "field", "ip" to arr("geoip:private", "geoip:ru"), "outboundTag" to "direct"))
    // server unreachable: everything else goes direct too instead of into a dead tunnel
    if (bypass) rules.put(obj("type" to "field", "inboundTag" to arr("socks", "dns"), "outboundTag" to "direct"))
    val account = arr(obj("user" to socks.user, "pass" to socks.pass))
    val inbounds = arr(obj(
        "tag" to "socks", "listen" to "127.0.0.1", "port" to socks.port, "protocol" to "socks",
        "settings" to obj("auth" to "password", "udp" to true, "accounts" to account),
        "sniffing" to obj("enabled" to true, "destOverride" to arr("http", "tls", "quic"), "routeOnly" to true),
    ))
    if (socks.probePort != 0) inbounds.put(obj(
        "tag" to "probe", "listen" to "127.0.0.1", "port" to socks.probePort, "protocol" to "socks",
        "settings" to obj("auth" to "password", "accounts" to account)))
    return obj(
        "log" to obj("loglevel" to "warning", "access" to "none"),
        "dns" to obj("servers" to dnsServers, "queryStrategy" to "UseIPv4", "tag" to "dns"),
        "inbounds" to inbounds,
        "outbounds" to arr(
            obj("protocol" to "vless", "tag" to "proxy",
                "settings" to obj("vnext" to arr(obj("address" to (serverIp ?: s.host), "port" to s.port,
                                                     "users" to arr(user)))),
                "streamSettings" to streamSettings(s)),
            // Go can't resolve names itself on Android: let Xray's DNS do it
            obj("protocol" to "freedom", "tag" to "direct", "settings" to obj("domainStrategy" to "UseIPv4")),
            obj("protocol" to "blackhole", "tag" to "block"),
        ),
        "routing" to obj("domainStrategy" to "AsIs", "rules" to rules),
    ).toString(2)
}

/** hev-socks5-tunnel: TUN fd -> Xray's SOCKS5; DNS answered with mapped addresses so Xray sees names. */
fun hevConfig(socks: Socks): String {
    fun q(v: String) = "'" + v.replace("'", "''") + "'"
    return """
        |tunnel:
        |  mtu: $TUN_MTU
        |  ipv4: $TUN_ADDR
        |socks5:
        |  port: ${socks.port}
        |  address: 127.0.0.1
        |  udp: 'udp'
        |  username: ${q(socks.user)}
        |  password: ${q(socks.pass)}
        |mapdns:
        |  address: $TUN_DNS
        |  port: 53
        |  network: $MAPPED_NET
        |  netmask: 255.255.0.0
        |  cache-size: 10000
        |misc:
        |  tcp-read-write-timeout: 300000
        |  udp-read-write-timeout: 60000
        |  log-level: warn
        |""".trimMargin()
}

// ----------------------------------------------------------------- routes --

private fun ipToLong(ip: String): Long =
    ip.split('.').fold(0L) { acc, part -> (acc shl 8) or part.toLong() }

private fun longToIp(v: Long) = "${v shr 24 and 255}.${v shr 16 and 255}.${v shr 8 and 255}.${v and 255}"

/** IPv4 routes covering everything except [excluded], as (address, prefix) pairs. */
fun routesExcluding(excluded: List<String>): List<Pair<String, Int>> {
    val holes = excluded.map {
        val (ip, len) = it.split('/')
        val start = ipToLong(ip) and (0xFFFFFFFFL shl (32 - len.toInt()) and 0xFFFFFFFFL)
        start to start + (1L shl (32 - len.toInt())) - 1
    }.sortedBy { it.first }
    val out = mutableListOf<Pair<String, Int>>()
    fun cover(from: Long, to: Long) {   // smallest CIDR set for [from, to]
        var a = from
        while (a <= to) {
            var len = 32
            while (len > 0) {
                val size = 1L shl (32 - (len - 1))
                if (a % size != 0L || a + size - 1 > to) break
                len--
            }
            out += longToIp(a) to len
            a += 1L shl (32 - len)
        }
    }
    var next = 0L
    for ((start, end) in holes) {
        if (start > next) cover(next, start - 1)
        next = maxOf(next, end + 1)
    }
    if (next <= 0xFFFFFFFFL) cover(next, 0xFFFFFFFFL)
    return out
}
