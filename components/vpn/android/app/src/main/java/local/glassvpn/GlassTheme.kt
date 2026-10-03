package local.glassvpn

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// The "glass" look: a dark aurora backdrop, frosted translucent surfaces with a light
// gradient rim, and one glowing orb. Everything is drawn with gradients — no blur, which
// Android 9 TVs can't do and their GPUs couldn't afford.

object GlassColors {
    val Base = Color(0xFF060912)
    val Text = Color(0xF2FFFFFF)
    val Dim = Color(0x9EFFFFFF)
    val Faint = Color(0x66FFFFFF)
    val Accent = Color(0xFF8EA4FF)
    val AccentGradient = listOf(Color(0xFF7C95FF), Color(0xFFB186FF), Color(0xFF5FD8CB))
    val Colors = darkColorScheme(
        primary = Accent, onPrimary = Color(0xFF0B1020),
        surface = Color(0xFF141A2A), onSurface = Text, surfaceVariant = Color(0xFF1C2336),
        background = Base, onBackground = Text, outline = Color(0x40FFFFFF),
    )
}

/** Full-screen backdrop: deep navy with soft colour blooms (static: drawn once, costs nothing). */
@Composable
internal fun Backdrop(@Suppress("UNUSED_PARAMETER") dark: Boolean = true, content: @Composable BoxScope.() -> Unit) {
    Box(Modifier.fillMaxSize().background(GlassColors.Base).drawBehind {
        fun bloom(x: Float, y: Float, r: Float, c: Color, a: Float) = drawCircle(
            Brush.radialGradient(listOf(c.copy(alpha = a), c.copy(alpha = a * 0.35f), Color.Transparent),
                                 center = Offset(size.width * x, size.height * y), radius = size.maxDimension * r),
            radius = size.maxDimension * r, center = Offset(size.width * x, size.height * y))
        bloom(0.12f, 0.18f, 0.55f, Color(0xFF2E5BFF), 0.42f)
        bloom(0.88f, 0.10f, 0.45f, Color(0xFF7A4DFF), 0.36f)
        bloom(0.78f, 0.95f, 0.55f, Color(0xFF13A89A), 0.30f)
        bloom(0.20f, 1.00f, 0.40f, Color(0xFF6A3DE8), 0.22f)
        // vignette keeps the edges calm on a big screen
        drawRect(Brush.radialGradient(listOf(Color.Transparent, Color.Black.copy(alpha = 0.45f)),
                                      center = center, radius = size.maxDimension * 0.75f))
    }, content = content)
}

/** Frosted glass: translucent fill brighter at the top, a rim of light along the edge. */
fun Modifier.glass(shape: Shape = RoundedCornerShape(28.dp), strength: Float = 1f): Modifier =
    this.background(Brush.verticalGradient(listOf(Color.White.copy(alpha = 0.11f * strength),
                                                  Color.White.copy(alpha = 0.035f * strength))), shape)
        .border(1.dp, Brush.linearGradient(listOf(Color.White.copy(alpha = 0.34f * strength),
                                                  Color.White.copy(alpha = 0.05f),
                                                  Color.White.copy(alpha = 0.16f * strength))), shape)

/** A glass card. [Glass] keeps its old call shape so every screen picks the new look up. */
@Composable
internal fun Glass(@Suppress("UNUSED_PARAMETER") dark: Boolean = true, modifier: Modifier = Modifier,
                   content: @Composable ColumnScope.() -> Unit) {
    val shape = RoundedCornerShape(28.dp)
    Column(modifier.glass(shape).padding(8.dp), content = content)
}

/** "Glass VPN" in light + bold with the accent gradient. */
@Composable
fun Wordmark(size: TextUnit = 26.sp, modifier: Modifier = Modifier) {
    Text(buildAnnotatedString {
        withStyle(SpanStyle(fontWeight = FontWeight.Light)) { append("Glass ") }
        withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append("VPN") }
    }, style = TextStyle(brush = Brush.linearGradient(GlassColors.AccentGradient), fontSize = size, letterSpacing = 0.5.sp),
         modifier = modifier)
}

/** Small frosted pill with optional leading content. */
@Composable
fun GlassChip(text: String, modifier: Modifier = Modifier, color: Color = GlassColors.Text,
              leading: (@Composable () -> Unit)? = null) {
    Row(modifier.glass(RoundedCornerShape(50), 0.8f).padding(horizontal = 12.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically) {
        if (leading != null) { leading(); Spacer(Modifier.width(6.dp)) }
        Text(text, fontSize = 13.sp, color = color, style = TextStyle(fontFeatureSettings = "tnum"))
    }
}

/** Three signal bars for a latency: green < 150 ms, amber < 400, red above or unknown. */
@Composable
fun SignalBars(ms: Int?, modifier: Modifier = Modifier, height: Dp = 14.dp) {
    val lit = when { ms == null -> 0; ms < 150 -> 3; ms < 400 -> 2; else -> 1 }
    val c = Color(stateColor(when (lit) { 3 -> VpnState.ON; 2 -> VpnState.CONNECTING; else -> VpnState.ERROR }))
    Canvas(modifier.size(width = height, height = height)) {
        val w = size.width / 5
        for (i in 0 until 3) {
            val h = size.height * (0.4f + 0.3f * i)
            drawRoundRect(if (i < lit) c else Color.White.copy(alpha = 0.18f),
                          topLeft = Offset(i * w * 2, size.height - h), size = Size(w, h),
                          cornerRadius = androidx.compose.ui.geometry.CornerRadius(w / 2))
        }
    }
}

/** Leading flag emoji of a server name ("🇪🇪 Tallinn"), if any, and the rest of the name. */
fun splitFlag(name: String): Pair<String?, String> {
    val cps = name.codePoints().toArray()
    fun regional(cp: Int) = cp in 0x1F1E6..0x1F1FF
    return if (cps.size >= 2 && regional(cps[0]) && regional(cps[1]))
        String(cps, 0, 2) to String(cps, 2, cps.size - 2).trim()
    else null to name
}

/** Round glass badge: the server's flag, or its first letter. */
@Composable
fun ServerBadge(name: String, size: Dp = 42.dp) {
    val (flag, rest) = splitFlag(name)
    Box(Modifier.size(size).glass(CircleShape, 0.9f), contentAlignment = Alignment.Center) {
        if (flag != null) Text(flag, fontSize = (size.value * 0.5f).sp)
        else Text(rest.take(1).uppercase(), fontSize = (size.value * 0.42f).sp, fontWeight = FontWeight.SemiBold,
                  style = TextStyle(brush = Brush.linearGradient(GlassColors.AccentGradient)))
    }
}

/** "VLESS · Reality · gRPC · ML-KEM" from a server's settings. */
fun Server.subtitle(): String = listOfNotNull(
    "VLESS",
    when (security) { "reality" -> "Reality"; "tls" -> "TLS"; else -> null },
    when (type) { "grpc" -> "gRPC"; "ws" -> "WebSocket"; "xhttp", "splithttp" -> "XHTTP"; "httpupgrade" -> "HTTPUpgrade"; else -> null },
    if (encryption.startsWith("mlkem")) "ML-KEM" else null,
).joinToString(" · ")

/**
 * The connect button: a glass sphere with a specular highlight, a status ring and a halo in
 * the state's colour — breathing while connected, a turning arc while connecting.
 */
@Composable
fun GlassOrb(state: VpnState, modifier: Modifier = Modifier, size: Dp = 200.dp, onClick: () -> Unit) {
    val t = rememberInfiniteTransition(label = "orb")
    val breathe by t.animateFloat(0.55f, 1f, infiniteRepeatable(tween(2600), RepeatMode.Reverse), label = "breathe")
    val spin by t.animateFloat(0f, 360f, infiniteRepeatable(tween(1300, easing = LinearEasing)), label = "spin")
    val tint by animateColorAsState(if (state == VpnState.OFF) Color.White else Color(stateColor(state)), label = "tint")
    Box(Modifier.size(size).drawBehind {
        // halo, drawn past the orb's bounds (nothing clips it)
        if (state != VpnState.OFF) {
            val a = if (state == VpnState.CONNECTING) 0.45f else 0.62f * breathe
            val r = this.size.minDimension * 1.05f
            // starts at the orb's edge (0.5 / 1.05 of the radius): the glass itself stays clear
            drawCircle(Brush.radialGradient(0.44f to Color.Transparent, 0.48f to tint.copy(alpha = a),
                                            0.68f to tint.copy(alpha = a * 0.3f), 1f to Color.Transparent, radius = r),
                       radius = r)
        }
    }, contentAlignment = Alignment.Center) {
        Box(modifier.fillMaxSize().focusRing(CircleShape, zoom = 1.05f, onClick = onClick)
                .background(Brush.radialGradient(listOf(Color.White.copy(alpha = 0.20f), Color.White.copy(alpha = 0.04f)),
                                                 center = Offset.Unspecified), CircleShape)
                .border(1.5.dp, Brush.linearGradient(listOf(Color.White.copy(alpha = 0.6f), Color.White.copy(alpha = 0.05f),
                                                            Color.White.copy(alpha = 0.25f))), CircleShape),
            contentAlignment = Alignment.Center) {
            Canvas(Modifier.fillMaxSize()) {
                val ring = 5.dp.toPx()
                val inset = 12.dp.toPx()
                val arcSize = Size(size.toPx() - inset * 2, size.toPx() - inset * 2)
                // status ring
                if (state == VpnState.CONNECTING) {
                    drawCircle(Color.White.copy(alpha = 0.10f), radius = arcSize.width / 2, style = Stroke(ring))
                    rotate(spin) {
                        drawArc(Brush.sweepGradient(listOf(Color.Transparent, tint, tint)), 0f, 300f, false,
                                topLeft = Offset(inset, inset), size = arcSize, style = Stroke(ring, cap = StrokeCap.Round))
                    }
                } else {
                    drawCircle(if (state == VpnState.OFF) Color.White.copy(alpha = 0.14f) else tint.copy(alpha = 0.95f),
                               radius = arcSize.width / 2, style = Stroke(ring))
                }
                // specular highlight on the upper left of the sphere
                drawArc(Color.White.copy(alpha = 0.28f), 200f, 70f, false,
                        topLeft = Offset(inset + ring * 2.2f, inset + ring * 2.2f),
                        size = Size(arcSize.width - ring * 4.4f, arcSize.height - ring * 4.4f),
                        style = Stroke(ring * 0.6f, cap = StrokeCap.Round))
            }
            Canvas(Modifier.size(size * 0.42f)) {
                val w = this.size.width
                val h = this.size.height
                val shield = Path().apply {
                    moveTo(w * 0.5f, h * 0.04f)
                    lineTo(w * 0.88f, h * 0.18f)
                    cubicTo(w * 0.88f, h * 0.55f, w * 0.75f, h * 0.80f, w * 0.5f, h * 0.96f)
                    cubicTo(w * 0.25f, h * 0.80f, w * 0.12f, h * 0.55f, w * 0.12f, h * 0.18f)
                    close()
                }
                if (state == VpnState.ON) drawPath(shield, Brush.verticalGradient(listOf(tint.copy(alpha = 0.30f), tint.copy(alpha = 0.06f))))
                drawPath(shield, Brush.verticalGradient(listOf(Color.White, Color.White.copy(alpha = 0.7f))),
                         style = Stroke(width = w * 0.07f, join = StrokeJoin.Round))
                if (state != VpnState.OFF) {
                    val c = Offset(w * 0.5f, h * 0.47f)
                    drawCircle(Brush.radialGradient(listOf(tint.copy(alpha = 0.6f), Color.Transparent), center = c, radius = w * 0.3f),
                               radius = w * 0.3f, center = c)
                    drawCircle(tint, radius = w * 0.12f, center = c)
                }
            }
        }
    }
}
