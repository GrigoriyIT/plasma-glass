package local.glassvpn

import android.app.UiModeManager
import android.content.Context
import android.content.pm.PackageManager
import android.content.res.Configuration
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import kotlinx.coroutines.delay

internal val FOCUS = Color.White   // a white glow reads on the dark glass and is no state colour

fun isTv(ctx: Context): Boolean =
    ctx.packageManager.hasSystemFeature(PackageManager.FEATURE_LEANBACK) ||
        ctx.getSystemService(UiModeManager::class.java).currentModeType == Configuration.UI_MODE_TYPE_TELEVISION

/**
 * Clickable that shows clearly where the remote's focus is: a coloured ring and a slight
 * zoom. On a phone nothing is focused, so it looks like a plain clickable there.
 */
fun Modifier.focusRing(shape: Shape = RoundedCornerShape(14.dp), zoom: Float = 1.04f, onClick: () -> Unit): Modifier =
    composed {
        var focused by remember { mutableStateOf(false) }
        // full-width rows pass zoom = 1: zoomed, they would stick out of their card
        val scale by animateFloatAsState(if (focused) zoom else 1f, label = "zoom")
        this.scale(scale)
            .onFocusChanged { focused = it.isFocused }
            .border(2.5.dp, if (focused) FOCUS.copy(alpha = 0.95f) else Color.Transparent, shape)
            .clip(shape)
            .background(if (focused) FOCUS.copy(alpha = 0.12f) else Color.Transparent)
            .clickable(onClick = onClick)
    }

/** Text action that is easy to see focused (Material's text buttons barely change on a TV). */
@Composable
fun LinkButton(text: String, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Text(text, fontSize = 14.sp, color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Medium,
         modifier = modifier.focusRing(RoundedCornerShape(10.dp), onClick = onClick).padding(horizontal = 10.dp, vertical = 8.dp))
}

/** Big labelled button for the TV main screen. */
@Composable
fun PillButton(text: String, @Suppress("UNUSED_PARAMETER") dark: Boolean = true, modifier: Modifier = Modifier,
               selected: Boolean = false, icon: androidx.compose.ui.graphics.vector.ImageVector? = null,
               onClick: () -> Unit) {
    val shape = RoundedCornerShape(50)
    Row(modifier.focusRing(shape, onClick = onClick)
            .then(if (selected) Modifier.background(Brush.linearGradient(GlassColors.AccentGradient.map { it.copy(alpha = 0.55f) }), shape)
                  else Modifier.glass(shape, 0.85f))
            .padding(horizontal = 18.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically) {
        if (icon != null) {
            androidx.compose.material3.Icon(icon, null, Modifier.size(18.dp), tint = GlassColors.Text)
            Spacer(Modifier.width(8.dp))
        }
        Text(text, fontSize = 15.sp, color = GlassColors.Text, fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal)
    }
}

/** Focus [requester] once the screen is shown (TV: the remote needs a starting point). */
@Composable
fun InitialFocus(requester: FocusRequester, enabled: Boolean = true) {
    LaunchedEffect(requester, enabled) {
        if (!enabled) return@LaunchedEffect
        delay(50)   // after the first layout
        try { requester.requestFocus() } catch (e: IllegalStateException) { }
    }
}

/**
 * "Add" on a TV: a QR code for the phone, which opens a page served by the TV on the LAN.
 * [onManual] falls back to typing with the remote.
 */
@Composable
fun AddFromPhoneDialog(dark: Boolean, onDismiss: () -> Unit, onText: (String) -> Unit, onManual: () -> Unit) {
    val ctx = LocalContext.current
    var url by remember { mutableStateOf<String?>(null) }
    var failed by remember { mutableStateOf(false) }
    DisposableEffect(Unit) {
        val srv = LanImport { text -> android.os.Handler(android.os.Looper.getMainLooper()).post { onText(text) } }
        url = try { srv.start(ctx) } catch (e: Exception) { null }
        failed = url == null
        onDispose { srv.stop() }
    }
    val focus = remember { FocusRequester() }
    Dialog(onDismissRequest = onDismiss) {
        Column(Modifier.background(Color(0xFC111726), RoundedCornerShape(32.dp)).glass(RoundedCornerShape(32.dp))
                   .padding(28.dp),
               horizontalAlignment = Alignment.CenterHorizontally) {
            Text("Добавить с телефона", fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(12.dp))
            val u = url
            if (u != null) {
                val bmp = remember(u) { LanImport.qr(u).asImageBitmap() }
                Image(bmp, "QR", Modifier.size(220.dp).clip(RoundedCornerShape(12.dp)))
                Spacer(Modifier.height(12.dp))
                Text("Наведите камеру телефона на код или откройте адрес в браузере телефона " +
                     "(телефон должен быть в той же сети):", fontSize = 14.sp, textAlign = TextAlign.Center)
                Text(u, fontSize = 15.sp, fontWeight = FontWeight.Medium, modifier = Modifier.padding(top = 6.dp))
            } else if (failed) {
                Text("Телевизор не подключён к Wi-Fi или Ethernet — добавьте вручную", fontSize = 14.sp,
                     textAlign = TextAlign.Center)
            }
            Spacer(Modifier.height(20.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                PillButton("Ввести вручную", dark, onClick = onManual)
                PillButton("Закрыть", dark, Modifier.focusRequester(focus), onClick = onDismiss)
            }
        }
    }
    InitialFocus(focus)
}
