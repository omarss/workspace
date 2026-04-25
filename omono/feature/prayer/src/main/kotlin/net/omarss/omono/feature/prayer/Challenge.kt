package net.omarss.omono.feature.prayer

// One multiple-choice question shown by the Fajr dismiss gate. The
// user has to answer REQUIRED_CORRECT of them correctly in a row
// before the athan can be stopped — the classic "anti-snooze"
// pattern that makes Fajr impossible to sleep through.
data class Challenge(
    val id: String,
    val category: ChallengeCategory,
    val stem: String,
    val options: List<String>,
    val correctIndex: Int,
    val explanation: String? = null,
) {
    init {
        require(options.size in 2..6) { "expected 2..6 options, got ${options.size}" }
        require(correctIndex in options.indices) {
            "correctIndex=$correctIndex out of bounds for ${options.size} options"
        }
    }
}

enum class ChallengeCategory(val display: String) {
    Sat("SAT"),
    Qiyas("Saudi Qiyas"),
    Math("Math"),
    ;

    companion object {
        fun fromStorage(raw: String?): ChallengeCategory? =
            entries.firstOrNull { it.name.equals(raw, ignoreCase = true) }
    }
}

// Tuned-for-Fajr anti-snooze: three correct answers in a row to
// dismiss. Anything less is too forgiving; anything more is cruel
// at 5 a.m.
const val FAJR_CHALLENGE_REQUIRED: Int = 3
