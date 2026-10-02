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

internal val FOCUS = Color(0xFF0A84FF)

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
            // blue, not green: green already means "connected"
            .border(3.dp, if (focused) FOCUS else Color.Transparent, shape)
            .clip(shape)
            .background(if (focused) FOCUS.copy(alpha = 0.10f) else Color.Transparent)
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
fun PillButton(text: String, dark: Boolean, modifier: Modifier = Modifier, selected: Boolean = false,
               onClick: () -> Unit) {
    val shape = RoundedCornerShape(50)
    Text(text, fontSize = 16.sp, textAlign = TextAlign.Center,
         color = if (selected) Color.White else Color.Unspecified,
         modifier = modifier.focusRing(shape, onClick = onClick)
             .background(when {
                 selected -> Color(0xFF3A3A3C)       // dark, not blue: blue is the focus
                 dark -> Color.White.copy(alpha = 0.10f)
                 else -> Color.White.copy(alpha = 0.6f)
             })
             .padding(horizontal = 20.dp, vertical = 12.dp))
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
        Column(Modifier.clip(RoundedCornerShape(28.dp))
                   .background(if (dark) Color(0xFF1C2436) else Color(0xFFF4F6FF)).padding(28.dp),
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
