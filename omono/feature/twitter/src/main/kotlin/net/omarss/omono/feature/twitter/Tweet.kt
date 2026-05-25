package net.omarss.omono.feature.twitter

// Domain model for one tweet rendered on the Twitter tab. Mirrors the
// JSON wire shape served by the homelab `tweets` service — keeping the
// data class flat (no nested author object) trades a tiny amount of
// structure for very obvious mapping code in TweetsClient.
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
)

enum class Country(val code: String, val label: String) {
    KSA("ksa", "Saudi Arabia"),
    Egypt("eg", "Egypt"),
    ;

    companion object {
        fun fromCode(code: String?): Country? = entries.firstOrNull { it.code == code }
    }
}
