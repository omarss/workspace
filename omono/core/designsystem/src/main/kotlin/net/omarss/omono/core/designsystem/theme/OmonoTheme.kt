package net.omarss.omono.core.designsystem.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

@Composable
fun OmonoTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    // Material You. On by default on Android 12+; off falls back to the
    // brand palette so the app looks consistent on every device.
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit,
) {
    val colors = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val context = LocalContext.current
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }
        darkTheme -> OmonoDarkColors
        else -> OmonoLightColors
    }

    MaterialTheme(
        colorScheme = colors,
        typography = OmonoTypography,
        content = content,
    )
}
