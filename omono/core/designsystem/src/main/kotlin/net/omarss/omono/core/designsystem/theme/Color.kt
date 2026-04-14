package net.omarss.omono.core.designsystem.theme

import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.ui.graphics.Color

// Omono brand palette — anchored on the icon's ring gradient (#3B82F6 mid,
// #1D4ED8 deep) with Material 3 role tokens derived from it. Keeping the
// definitions co-located here makes it easy to tweak the brand without
// chasing them across screens.

private val BrandPrimary = Color(0xFF2563EB)
private val BrandPrimaryContainer = Color(0xFFDBEAFE)
private val BrandOnPrimary = Color(0xFFFFFFFF)
private val BrandOnPrimaryContainer = Color(0xFF0B1A3F)

private val BrandPrimaryDark = Color(0xFF93C5FD)
private val BrandPrimaryContainerDark = Color(0xFF1E3A8A)
private val BrandOnPrimaryDark = Color(0xFF0B1A3F)
private val BrandOnPrimaryContainerDark = Color(0xFFDBEAFE)

private val BrandSecondary = Color(0xFF475569)
private val BrandSecondaryContainer = Color(0xFFE2E8F0)

private val BrandTertiary = Color(0xFF0EA5E9)
private val BrandTertiaryContainer = Color(0xFFBAE6FD)

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
    onTertiaryContainer = Color(0xFF082F49),
    background = Color(0xFFF8FAFC),
    onBackground = Color(0xFF0F172A),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF0F172A),
    surfaceVariant = Color(0xFFEDF1F7),
    onSurfaceVariant = Color(0xFF475569),
    surfaceTint = BrandPrimary,
    outline = Color(0xFFCBD5E1),
    outlineVariant = Color(0xFFE2E8F0),
    error = Color(0xFFB42318),
    onError = Color.White,
    errorContainer = Color(0xFFFEE4E2),
    onErrorContainer = Color(0xFF7A271A),
)

internal val OmonoDarkColors = darkColorScheme(
    primary = BrandPrimaryDark,
    onPrimary = BrandOnPrimaryDark,
    primaryContainer = BrandPrimaryContainerDark,
    onPrimaryContainer = BrandOnPrimaryContainerDark,
    secondary = Color(0xFF94A3B8),
    onSecondary = Color(0xFF0F172A),
    secondaryContainer = Color(0xFF334155),
    onSecondaryContainer = Color(0xFFE2E8F0),
    tertiary = Color(0xFF7DD3FC),
    onTertiary = Color(0xFF082F49),
    tertiaryContainer = Color(0xFF075985),
    onTertiaryContainer = Color(0xFFBAE6FD),
    background = Color(0xFF0B1220),
    onBackground = Color(0xFFE2E8F0),
    surface = Color(0xFF111827),
    onSurface = Color(0xFFE2E8F0),
    surfaceVariant = Color(0xFF1F2937),
    onSurfaceVariant = Color(0xFF94A3B8),
    surfaceTint = BrandPrimaryDark,
    outline = Color(0xFF374151),
    outlineVariant = Color(0xFF1F2937),
    error = Color(0xFFF87171),
    onError = Color(0xFF450A0A),
    errorContainer = Color(0xFF7F1D1D),
    onErrorContainer = Color(0xFFFECACA),
)
