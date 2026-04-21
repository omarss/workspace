package net.omarss.omono.feature.quiz

// Domain types for the MCQ quiz feature. Names mirror the server
// schema in `omono/FEEDBACK.md §10` — when the contract evolves the
// lockstep rule is to update that document first, then these types
// second.

// Taxonomy — one subject (e.g. "argocd", "apple-pay"), many topics.
data class Subject(
    val slug: String,
    val title: String,
    val totalQuestions: Int,
    val roundsCovered: Int,
)

data class Topic(
    val subject: String,
    val slug: String,
    val title: String,
    val questionCount: Int,
)

// Three question types — `QuestionType.Any` is the client's sentinel
// for "don't filter"; the server just drops the `type=` param when
// that value is selected.
enum class QuestionType(val wireName: String?) {
    Any(null),
    Knowledge("knowledge"),
    Analytical("analytical"),
    ProblemSolving("problem_solving"),
    ;

    companion object {
        fun fromWire(raw: String?): QuestionType =
            entries.firstOrNull { it.wireName == raw } ?: Any
    }
}

// One eight-letter option. `isCorrect` is null on /quiz (hidden) and
// populated on /questions/{id}. The server returns the letters in a
// randomised order per call, so clients must treat (id, text) as the
// identity — never the letter.
data class QuizOption(
    val letter: String,
    val text: String,
    val isCorrect: Boolean?,
)

// One MCQ question. `options` is always exactly eight entries. When
// the question came from /quiz, `explanation` is null and every
// option's `isCorrect` is null. After revealing via /questions/{id}
// both are populated.
data class Question(
    val id: Int,
    val subject: String,
    val type: QuestionType,
    val round: Int,
    val difficulty: Int,
    val stem: String,
    val options: List<QuizOption>,
    val explanation: String?,
    val topics: List<String>,
)
