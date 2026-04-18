package net.omarss.omono.feature.speed

// Short, imperative phrases the voice alert can utter. Kept intentionally
// tight so they fit inside the ~2 s window a driver is actually going to
// notice between glances at the road. Pairs of (English, Arabic) — the
// player picks one based on the user's language preference.
enum class VoiceAlertPhrase(val english: String, val arabic: String) {
    // Over-limit: a direct imperative beats a description. "Slow down"
    // / "خفف السرعة" both land in well under a second.
    OVER_LIMIT(english = "Slow down", arabic = "خفف السرعة"),

    // Phone-use distraction: tells the driver what to do, not what
    // they're doing wrong. Feels less nagging on repeat.
    PHONE_USE(english = "Eyes on the road", arabic = "انتبه للطريق"),
}

// Language selection for voice alerts. "Auto" picks Arabic if the
// device locale starts with `ar`, English otherwise. Letting the user
// override is useful for bilingual drivers who want the opposite of
// what their phone UI is set to.
enum class VoiceAlertLanguage {
    Auto,
    English,
    Arabic,
    ;

    companion object {
        fun fromStorage(raw: String?): VoiceAlertLanguage =
            entries.firstOrNull { it.name == raw } ?: Auto
    }
}
