package net.omarss.omono.feature.twitter

// Domain model for one tweet rendered on the Feed tab. Mirrors the JSON
// wire shape served by the homelab `tweets` service — flat (no nested
// author object) to keep the mapping code in TweetsClient obvious.
data class Tweet(
    val id: String,
    val author: String,
    val handle: String,
    val text: String,
    // Epoch millis; the wire format is RFC3339 but we convert at parse
    // time so downstream UI / sorting code doesn't deal with strings.
    val createdAtMillis: Long,
    val lang: String?,
    val place: String?,
    val country: Country,
    val replyCount: Int,
    val likeCount: Int,
    val retweetCount: Int,
    // Service-side heuristic score in [0, 1]. The service drops anything
    // above its threshold before serving, so what reaches the client is
    // already "passed the filter" — borderline values can still nudge UI
    // (e.g. de-emphasise rows above 0.4).
    val spamScore: Float,
    // Event-relevance score in [0, 1]. Higher = more ticket / festival /
    // workshop / conference signal. The server's first page is already
    // sorted by this descending, so the UI can render badges directly
    // without re-sorting.
    val eventScore: Float = 0f,
    // Categories that contributed to the event score: any of `ticket`,
    // `registration`, `concert`, `festival`, `conference`, `workshop`,
    // `talk`, `sports`, `opening`, `venue`, `schedule`. Empty when the
    // tweet has no event signal.
    val eventCategories: List<String> = emptyList(),
    // Avatar URL (Twitter `_normal` ~48x48 variant). Empty when the
    // upstream omits it; UI should fall back to an author-initial chip.
    val avatarUrl: String? = null,
)

// Country enum used internally to model the broad "feed" tab. The
// network layer carries comma-separated lists per request; `code` is
// the lowercase wire token, `label` is the human display.
enum class Country(val code: String, val label: String) {
    KSA("ksa", "Saudi Arabia"),
    Egypt("eg", "Egypt"),
    ;

    companion object {
        fun fromCode(code: String?): Country? = entries.firstOrNull { it.code == code }
    }
}
