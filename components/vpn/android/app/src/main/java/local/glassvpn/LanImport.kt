package local.glassvpn

import android.content.Context
import android.graphics.Bitmap
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.util.Log
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import java.io.BufferedInputStream
import java.net.Inet4Address
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.net.URLDecoder
import java.security.SecureRandom
import kotlin.concurrent.thread

/**
 * Typing a 1700-character vless:// key with a TV remote is hopeless: while the "add" dialog
 * is open, a phone on the same network opens http://<tv>:<port>/<secret> (from a QR code)
 * and pastes the subscription there. Only one secret path answers, and only while open.
 */
class LanImport(private val onText: (String) -> Unit) {
    private val secret = ByteArray(8).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
    private var server: ServerSocket? = null

    /** Starts listening; returns the URL to show, or null without a local network. */
    fun start(ctx: Context): String? {
        val ip = localIpv4(ctx) ?: return null
        val s = ServerSocket(0)
        server = s
        thread(isDaemon = true, name = "lan-import") {
            while (!s.isClosed) {
                try {
                    val c = s.accept()
                    thread(isDaemon = true) { c.use { serve(it) } }
                } catch (e: SocketException) {
                    break   // closed
                }
            }
        }
        return "http://$ip:${s.localPort}/$secret"
    }

    fun stop() {
        try { server?.close() } catch (e: Exception) { }
        server = null
    }

    private fun serve(c: Socket) {
        c.soTimeout = 15000
        try {
            val inp = BufferedInputStream(c.getInputStream())
            fun line(): String {
                val b = StringBuilder()
                while (true) {
                    val ch = inp.read()
                    if (ch < 0 || ch == '\n'.code) break
                    if (ch != '\r'.code) b.append(ch.toChar())
                    if (b.length > 8192) throw java.io.IOException("header too long")
                }
                return b.toString()
            }
            val (method, path) = line().split(' ').let { (it.getOrNull(0) ?: "") to (it.getOrNull(1) ?: "") }
            var length = 0
            while (true) {
                val h = line()
                if (h.isEmpty()) break
                if (h.startsWith("content-length:", ignoreCase = true)) length = h.substringAfter(':').trim().toIntOrNull() ?: 0
            }
            if (path.substringBefore('?') != "/$secret") return reply(c, 404, "Not found")
            when (method) {
                "GET" -> reply(c, 200, PAGE)
                "POST" -> {
                    if (length !in 1..262144) return reply(c, 413, page("Слишком длинный текст"))
                    val body = ByteArray(length)
                    var off = 0
                    while (off < length) { val r = inp.read(body, off, length - off); if (r < 0) break; off += r }
                    val form = String(body, 0, off, Charsets.UTF_8)
                    val text = form.split('&').firstOrNull { it.startsWith("text=") }
                        ?.let { URLDecoder.decode(it.removePrefix("text="), "UTF-8") }.orEmpty()
                    if (text.isBlank()) return reply(c, 400, page("Пусто — вставьте ссылку или ключ"))
                    onText(text)
                    reply(c, 200, page("Готово ✓ Смотрите на экран телевизора. Эту страницу можно закрыть."))
                }
                else -> reply(c, 405, "Method not allowed")
            }
        } catch (e: Exception) {
            Log.w("GlassVPN", "lan import: ${e.message}")
        }
    }

    private fun reply(c: Socket, code: Int, html: String) {
        val body = html.toByteArray()
        val head = "HTTP/1.1 $code OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: ${body.size}\r\n" +
                   "Cache-Control: no-store\r\nConnection: close\r\n\r\n"
        c.getOutputStream().apply { write(head.toByteArray()); write(body); flush() }
    }

    companion object {
        private const val STYLE = "<meta name=viewport content='width=device-width,initial-scale=1'>" +
            "<style>body{font:17px system-ui,sans-serif;margin:0;padding:20px;background:#eef2ff;color:#1c1c1e}" +
            "textarea{width:100%;box-sizing:border-box;height:45vh;font:14px monospace;padding:10px;border-radius:12px;border:1px solid #bbc}" +
            "button{margin-top:12px;width:100%;padding:14px;font-size:18px;border:0;border-radius:12px;background:#34c759;color:#fff}" +
            "@media(prefers-color-scheme:dark){body{background:#121a2a;color:#eee}textarea{background:#1c2436;color:#eee;border-color:#334}}</style>"
        private val PAGE = "<!doctype html><html lang=ru><head><meta charset=utf-8>$STYLE<title>Glass VPN</title></head><body>" +
            "<h2>Glass VPN → телевизор</h2><p>Вставьте ссылку на подписку (https://…) или ключи vless:// — по одному в строке.</p>" +
            "<form method=post><textarea name=text autofocus></textarea><button>Отправить на телевизор</button></form></body></html>"
        private fun page(msg: String) =
            "<!doctype html><html lang=ru><head><meta charset=utf-8>$STYLE<title>Glass VPN</title></head><body><h2>$msg</h2></body></html>"

        /** The device's address on the physical LAN (Wi-Fi or Ethernet). */
        fun localIpv4(ctx: Context): String? {
            val cm = ctx.getSystemService(ConnectivityManager::class.java)
            @Suppress("DEPRECATION")
            return cm.allNetworks.filter { n ->
                cm.getNetworkCapabilities(n)?.let {
                    it.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN) &&
                        (it.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) || it.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET))
                } == true
            }.firstNotNullOfOrNull { n ->
                cm.getLinkProperties(n)?.linkAddresses?.map { it.address }?.firstOrNull { it is Inet4Address }?.hostAddress
            }
        }

        fun qr(text: String, size: Int = 512): Bitmap {
            val m = QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, size, size, mapOf(EncodeHintType.MARGIN to 1))
            val px = IntArray(size * size) { if (m[it % size, it / size]) 0xFF000000.toInt() else 0xFFFFFFFF.toInt() }
            return Bitmap.createBitmap(px, size, size, Bitmap.Config.ARGB_8888)
        }
    }
}
