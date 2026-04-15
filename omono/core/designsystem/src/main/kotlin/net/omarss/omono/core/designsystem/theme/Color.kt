package net.omarss.omono.core.designsystem.theme

import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.ui.graphics.Color

// Omono brand palette — High contrast OLED black and striking electric indigo.

private val BrandPrimary = Color(0xFF4F46E5) // Indigo 600
private val BrandPrimaryContainer = Color(0xFFE0E7FF) // Indigo 100
private val BrandOnPrimary = Color(0xFFFFFFFF)
private val BrandOnPrimaryContainer = Color(0xFF1E1B4B) // Indigo 900

private val BrandPrimaryDark = Color(0xFF818CF8) // Indigo 400
private val BrandPrimaryContainerDark = Color(0xFF3730A3) // Indigo 800
private val BrandOnPrimaryDark = Color(0xFF0F172A)
private val BrandOnPrimaryContainerDark = Color(0xFFE0E7FF)

private val BrandSecondary = Color(0xFF14B8A6) // Teal 500
private val BrandSecondaryContainer = Color(0xFFCCFBF1) // Teal 100

private val BrandTertiary = Color(0xFF8B5CF6) // Violet 500
private val BrandTertiaryContainer = Color(0xFFEDE9FE) // Violet 100

internal val OmonoLightColors = lightColorScheme(
    primary = BrandPrimary,
    onPrimary = BrandOnPrimary,
    primaryContainer = BrandPrimaryContainer,
    onPrimaryContainer = BrandOnPrimaryContainer,
    secondary = BrandSecondary,
    onSecondary = Color.White,
    secondaryContainer = BrandSecondaryContainer,
    onSecondaryContainer = Color(0xFF0F172A),
    tertiary = BrandTertiary,
    onTertiary = Color.White,
    tertiaryContainer = BrandTertiaryContainer,
    onTertiaryContainer = Color(0xFF2E1065), // Violet 900
    background = Color(0xFFF8FAFC),
    onBackground = Color(0xFF0F172A),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF0F172A),
    surfaceVariant = Color(0xFFF1F5F9), // Slate 100
    onSurfaceVariant = Color(0xFF475569),
    surfaceTint = BrandPrimary,
    outline = Color(0xFFCBD5E1),
    outlineVariant = Color(0xFFE2E8F0),
    error = Color(0xFFDC2626), // Red 600
    onError = Color.White,
    errorContainer = Color(0xFFFEF2F2), // Red 50
    onErrorContainer = Color(0xFF7F1D1D), // Red 900
)

internal val OmonoDarkColors = darkColorScheme(
    primary = BrandPrimaryDark,
    onPrimary = BrandOnPrimaryDark,
    primaryContainer = BrandPrimaryContainerDark,
    onPrimaryContainer = BrandOnPrimaryContainerDark,
    secondary = Color(0xFF5EEAD4), // Teal 300
    onSecondary = Color(0xFF042F2E), // Teal 900
    secondaryContainer = Color(0xFF134E4A), // Teal 900
    onSecondaryContainer = Color(0xFFCCFBF1),
    tertiary = Color(0xFFA78BFA), // Violet 400
    onTertiary = Color(0xFF2E1065),
    tertiaryContainer = Color(0xFF4C1D95), // Violet 900
    onTertiaryContainer = Color(0xFFEDE9FE),
    background = Color(0xFF000000), // OLED Black
    onBackground = Color(0xFFF8FAFC),
    surface = Color(0xFF0B0F19), // Ultra-dark gray/blue
    onSurface = Color(0xFFF1F5F9),
    surfaceVariant = Color(0xFF1E293B), // Slate 800
    onSurfaceVariant = Color(0xFF94A3B8),
    surfaceTint = BrandPrimaryDark,
    outline = Color(0xFF334155),
    outlineVariant = Color(0xFF0F172A),
    error = Color(0xFFF87171),
    onError = Color(0xFF450A0A),
    errorContainer = Color(0xFF7F1D1D),
    onErrorContainer = Color(0xFFFECACA),
)
