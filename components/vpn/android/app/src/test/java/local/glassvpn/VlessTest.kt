package local.glassvpn

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.util.Base64

class VlessTest {
    // throwaway keys from `xray x25519` / `xray vlessenc`, so a desktop Xray accepts the config
    private val reality = "vless://0b7d1d3e-1111-2222-3333-444455556666@vpn.example.com:8443" +
        "?type=grpc&security=reality&sni=www.microsoft.com&fp=chrome&pbk=nTmzCJOluFuIVEbh9EnN3z00k_Zfw-w6SXJqAe8zESU" +
        "&sid=6ba85179e30d4fc2&serviceName=grpc&encryption=mlkem768x25519plus.native.0rtt.lqRwSEy0Qg1Iv53kUBgqhr0-2evyjFl0YD7Aq51ibis" +
        "#%F0%9F%87%AA%F0%9F%87%AA%20Estonia"

    @Test fun parsesReality() {
        val s = parseVless(reality)!!
        assertEquals("🇪🇪 Estonia", s.name)
        assertEquals("vpn.example.com", s.host)
        assertEquals(8443, s.port)
        assertEquals("grpc", s.type)
        assertEquals("reality", s.security)
        assertEquals("www.microsoft.com", s.sni)
        assertEquals("nTmzCJOluFuIVEbh9EnN3z00k_Zfw-w6SXJqAe8zESU", s.pbk)
        assertEquals("grpc", s.serviceName)
        assertEquals("mlkem768x25519plus.native.0rtt.lqRwSEy0Qg1Iv53kUBgqhr0-2evyjFl0YD7Aq51ibis", s.encryption)
    }

    @Test fun parsesIpv6AndDefaults() {
        val s = parseVless("vless://id@[2001:db8::1]:443")!!
        assertEquals("2001:db8::1", s.host)
        assertEquals("tcp", s.type)
        assertEquals("none", s.encryption)
        assertEquals("2001:db8::1:443", s.name)
        assertNull(parseVless("vmess://abc"))
        assertNull(parseVless("vless://hostonly:443"))
        assertNull(parseVless("vless://id@host:99999"))
    }

    @Test fun decodesBase64Subscription() {
        val body = Base64.getEncoder().encodeToString("$reality\nvless://id@h:1#two\ngarbage\n".toByteArray())
        val list = decodeSubscription(body.chunked(60).joinToString("\n"))
        assertEquals(listOf("🇪🇪 Estonia", "two"), list.map { it.name })
        assertEquals(2, decodeSubscription("$reality\nvless://id@h:1#two").size)
    }

    @Test fun serverJsonRoundTrip() {
        val s = parseVless(reality)!!.copy(manual = true)
        assertEquals(s, Server.fromJson(JSONObject(s.toJson().toString())))
    }

    @Test fun xrayConfigShape() {
        val s = parseVless(reality)!!
        val cfg = JSONObject(xrayConfig(s, "203.0.113.7", Socks(12345, "u", "p"), listOf("192.168.1.1")))
        val inbound = cfg.getJSONArray("inbounds").getJSONObject(0)
        assertEquals("127.0.0.1", inbound.getString("listen"))
        assertEquals("password", inbound.getJSONObject("settings").getString("auth"))
        val out = cfg.getJSONArray("outbounds").getJSONObject(0)
        assertEquals("proxy", out.getString("tag"))
        val vnext = out.getJSONObject("settings").getJSONArray("vnext").getJSONObject(0)
        assertEquals("203.0.113.7", vnext.getString("address"))
        assertEquals(s.encryption, vnext.getJSONArray("users").getJSONObject(0).getString("encryption"))
        val stream = out.getJSONObject("streamSettings")
        assertEquals("grpc", stream.getString("network"))
        assertEquals("nTmzCJOluFuIVEbh9EnN3z00k_Zfw-w6SXJqAe8zESU", stream.getJSONObject("realitySettings").getString("publicKey"))
        assertFalse(cfg.toString().contains("\"flow\""))   // empty flow is left out
        System.getenv("GLASSVPN_DUMP")?.let { File(it).writeText(cfg.toString(2)) }
    }

    @Test fun probeAndBypass() {
        val s = parseVless(reality)!!
        val socks = Socks(12345, "u", "p", 12346)
        fun rules(c: JSONObject) = c.getJSONObject("routing").getJSONArray("rules").let { r ->
            List(r.length()) { r.getJSONObject(it) } }
        val normal = JSONObject(xrayConfig(s, "203.0.113.7", socks, listOf("192.168.1.1")))
        val bypass = JSONObject(xrayConfig(s, "203.0.113.7", socks, listOf("192.168.1.1"), bypass = true))
        // the probe port is a second inbound, routed to the server first in both modes
        assertEquals(12346, normal.getJSONArray("inbounds").getJSONObject(1).getInt("port"))
        for (c in listOf(normal, bypass)) {
            val first = rules(c).first()
            assertEquals("probe", first.getJSONArray("inboundTag").getString(0))
            assertEquals("proxy", first.getString("outboundTag"))
        }
        // bypass ends with "everything from the apps and DNS goes direct"; normal falls through to proxy
        val last = rules(bypass).last()
        assertEquals("direct", last.getString("outboundTag"))
        assertEquals(listOf("socks", "dns"), last.getJSONArray("inboundTag").let { a -> List(a.length()) { a.getString(it) } })
        assertEquals(rules(normal).size + 1, rules(bypass).size)
        // the network's DNS answers Russian names first and is the fallback after DoH
        val dns = normal.getJSONObject("dns").getJSONArray("servers")
        assertTrue(dns.get(0) is JSONObject && dns.getJSONObject(0).has("domains"))
        assertEquals("https://1.1.1.1/dns-query", dns.getString(1))
        assertFalse(dns.getJSONObject(2).has("domains"))
        System.getenv("GLASSVPN_DUMP_BYPASS")?.let { File(it).writeText(bypass.toString(2)) }
    }

    @Test fun hevConfigQuotes() {
        val y = hevConfig(Socks(1080, "a'b", "c"))
        assertTrue(y.contains("username: 'a''b'"))
        assertTrue(y.contains("mapdns:"))
    }

    @Test fun routesCoverEverythingButExcluded() {
        val routes = routesExcluding(EXCLUDED_NETS)
        fun range(ip: String, len: Int): LongRange {
            val v = ip.split('.').fold(0L) { a, p -> (a shl 8) or p.toLong() }
            return v until v + (1L shl (32 - len))
        }
        val total = routes.sumOf { (ip, len) -> 1L shl (32 - len) }
        val excluded = EXCLUDED_NETS.sumOf { 1L shl (32 - it.substringAfter('/').toInt()) }
        assertEquals((1L shl 32) - excluded, total)
        val holes = EXCLUDED_NETS.map { val (ip, l) = it.split('/'); range(ip, l.toInt()) }
        for ((ip, len) in routes) {
            val r = range(ip, len)
            assertTrue("$ip/$len aligned", r.first % (1L shl (32 - len)) == 0L)
            for (h in holes) assertTrue("$ip/$len overlaps $h", r.last < h.first || r.first > h.last)
        }
        // the TUN and mapped-DNS ranges must be routed into the tunnel
        assertNotNull(routes.firstOrNull { (ip, len) -> range(ip, len).contains(range("198.19.0.0", 16).first) })
    }
}
