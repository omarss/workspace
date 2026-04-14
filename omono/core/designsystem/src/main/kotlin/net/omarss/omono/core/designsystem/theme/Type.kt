package net.omarss.omono.core.designsystem.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Extends the default Material 3 typography with an oversized display
// scale for the hero speed readout on the main screen. Everything else
// inherits from M3 defaults so body/label/title text stays consistent
// with standard Material spacing.
private val Base = Typography()

private val HeroNumber = TextStyle(
    fontFamily = FontFamily.SansSerif,
    fontWeight = FontWeight.Black,
    fontSize = 112.sp,
    lineHeight = 112.sp,
    letterSpacing = (-4).sp,
)

internal val OmonoTypography = Base.copy(
    displayLarge = HeroNumber,
    displayMedium = Base.displayMedium.copy(
        fontWeight = FontWeight.ExtraBold,
        letterSpacing = (-1).sp,
    ),
    headlineLarge = Base.headlineLarge.copy(
        fontWeight = FontWeight.Bold,
        letterSpacing = (-0.5).sp,
    ),
    titleLarge = Base.titleLarge.copy(fontWeight = FontWeight.SemiBold),
    labelLarge = Base.labelLarge.copy(fontWeight = FontWeight.SemiBold),
)
