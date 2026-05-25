package net.omarss.omono.core.designsystem.theme

import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

// Cross-cutting semantic colour tokens. Material 3's colorScheme handles
// surface / primary / error well, but the app has a second axis of
// meaning that doesn't map cleanly to MD3 roles:
//   * money flow direction (in vs. overspend vs. neutral)
//   * transaction kind tints (transfer, ATM, bill) used in icon badges
//   * status traffic lights (good / warn / danger) used across Tracking,
//     Compass, Places, and Prayer
//   * an accent gold for ratings and qibla — same hue as the warn token
//     but a distinct intent (heritage / highlight, not "needs attention")
//
// Centralising these here unblocks two things:
//  1. one-file retunes (Phase 2): change a value here, every call site
//     follows automatically.
//  2. paired-variant correctness: incomeSoft is always the pastel of
//     income, dangerOnHero is always the gradient-legible danger, etc.
//     Today those pairings live as inline #hex literals next to each
//     other and silently drift apart.
//
// Out of scope: per-category identity palettes (PlaceCategoryIcons,
// finance category icon tints). Those are a categorical palette, not a
// semantic axis — keep them as their own thing.
@Immutable
data class OmonoSemanticColors(
    // Positive direction — money in, status good, "open", correct answer.
    val income: Color,
    // Soft pastel fill for highlighted backgrounds (quiz correct option,
    // success cards).
    val incomeSoft: Color,
    // Gradient-legible variant for hero cards painted on the indigo→violet
    // gradient — the regular income green washes out.
    val incomeOnHero: Color,

    // Negative direction — overspend, errors, wrong answer, declined.
    val danger: Color,
    val dangerSoft: Color,
    val dangerOnHero: Color,

    // Outgoing transfer tint (icon badges + amount text on the Transfers
    // card). Indigo-leaning so it sits beside the income green without
    // reading as another "in" colour.
    val transferOut: Color,
    // ATM cash withdrawal tint — violet so it's distinct from both money
    // flow directions and from the bill-neutral grey.
    val cashWithdraw: Color,
    // Utilities / bills tint — quiet slate so the badge reads as
    // "infrastructure" rather than calling attention to itself.
    val billNeutral: Color,

    // Status — caution (battery not exempt, GPS not yet fixed). Same hue
    // as accentGold today; kept separate so Phase 2 can differentiate
    // intent without a coordinated edit.
    val warning: Color,

    // Accent — rating stars, Qibla marker, "heritage" highlights.
    val accentGold: Color,
)

// Phase 1 values are deliberately identical to the inline literals they
// replace, so the migration introduces zero visual change. Phase 2 will
// retune these toward warmer neutrals + deeper money greens.
internal val OmonoSemanticLight = OmonoSemanticColors(
    income = Color(0xFF10B981),         // emerald 500
    incomeSoft = Color(0xFFDCFCE7),     // emerald 100
    incomeOnHero = Color(0xFFA7F3D0),   // emerald 200 — readable on gradient
    danger = Color(0xFFDC2626),         // red 600
    dangerSoft = Color(0xFFFEE2E2),     // red 100
    dangerOnHero = Color(0xFFF87171),   // red 400 — readable on gradient
    transferOut = Color(0xFF6366F1),    // indigo 500
    cashWithdraw = Color(0xFF8B5CF6),   // violet 500
    billNeutral = Color(0xFF64748B),    // slate 500
    warning = Color(0xFFF59E0B),        // amber 500
    accentGold = Color(0xFFF59E0B),     // amber 500
)

// Dark-mode values match light for Phase 1. The original inline literals
// were never differentiated by theme — they were chosen to read on the
// indigo→violet gradient hero, which is the same in both modes. Phase 2
// will introduce real dark-mode variants (slightly lighter income, less
// saturated danger) once we've validated the structural refactor.
internal val OmonoSemanticDark = OmonoSemanticLight

val LocalOmonoSemantic = staticCompositionLocalOf<OmonoSemanticColors> {
    error(
        "OmonoSemanticColors not provided — wrap your content in OmonoTheme { ... } " +
            "from core:designsystem.",
    )
}

// Access point for semantic tokens. Mirrors the MaterialTheme.colorScheme
// shape so call sites read the same way:
//   val income = OmonoTokens.colors.income
object OmonoTokens {
    val colors: OmonoSemanticColors
        @Composable
        @ReadOnlyComposable
        get() = LocalOmonoSemantic.current
}
