package net.omarss.omono.feature.spending

import net.omarss.omono.feature.spending.Transaction.Bank
import net.omarss.omono.feature.spending.Transaction.Kind

// Pure-Kotlin parser for bank transaction SMSes. Returns null for any
// message that isn't a successful consumer spending event we want to
// track — OTPs, declines, transfers, gold-selling, and anything from
// an unknown sender. Timestamp is not parsed from the body; callers
// should pair the return value with the SMS inbox row's DATE column.
object SmsParser {

    fun isKnownSender(address: String?): Boolean =
        address != null && (address.matchesAlRajhi() || address.matchesStcBank())

    fun parse(address: String?, body: String): ParsedSms? {
        if (address == null) return null
        return when {
            address.matchesAlRajhi() -> parseAlRajhi(body)
            address.matchesStcBank() -> parseStcBank(body)
            else -> null
        }
    }

    // ── AlRajhi ──────────────────────────────────────────────────────────
    //
    // Shapes we capture:
    //   "PoS\nBy:…\nAmount:SAR 72.05\nAt:ALDREES 4\n…"
    //   "Amount:SAR 1000\nBiller:207\nService:STC PAY\nBill:…"
    //
    // Shapes we skip:
    //   "OTP Code:…"
    //   "Transaction Declined:…"
    //   "Selling Gold Amount:SAR …" (income, not spending)
    //   "Debit Internal Transfer …" / "Rajhi Transfer …" (own-account moves)
    private fun parseAlRajhi(body: String): ParsedSms? {
        if (body.containsIgnoreCase("OTP Code")) return null
        if (body.containsIgnoreCase("Declined")) return null
        if (body.containsIgnoreCase("Selling Gold")) return null
        if (body.containsIgnoreCase("Internal Transfer")) return null
        if (body.containsIgnoreCase("Rajhi Transfer")) return null

        val amount = extractAlRajhiAmount(body) ?: return null
        val kind = when {
            body.containsIgnoreCase("PoS") -> Kind.POS
            body.contains("Biller:", ignoreCase = true) -> Kind.BILLER
            body.containsIgnoreCase("Online Purchase") -> Kind.ONLINE_PURCHASE
            else -> return null
        }
        val merchant = AL_RAJHI_MERCHANT_RE.find(body)?.groupValues?.get(1)?.trim()
        return ParsedSms(amount, Bank.AL_RAJHI, kind, merchant?.ifBlank { null })
    }

    // ── STC Bank ────────────────────────────────────────────────────────
    //
    // Shapes we capture:
    //   "Online Purchase Transaction\nAmount 57 SAR\nFrom: Jahez\nCard: *6066\nDate …"
    //   "Online Purchase Transaction\nAmount 111.75\nFrom: Ninja Retail Company\n…"
    //
    // Shapes we skip:
    //   "… is your OTP For:…"
    //   "Please use one time password …"
    //   "The transaction is not allowed…"
    private fun parseStcBank(body: String): ParsedSms? {
        if (body.containsIgnoreCase("is your OTP")) return null
        if (body.containsIgnoreCase("one time password")) return null
        if (body.containsIgnoreCase("not allowed")) return null
        if (body.containsIgnoreCase("Do not share")) return null

        if (!body.containsIgnoreCase("Online Purchase Transaction") &&
            !body.containsIgnoreCase("POS Transaction")
        ) return null

        val amount = extractStcAmount(body) ?: return null
        val kind = when {
            body.containsIgnoreCase("POS Transaction") -> Kind.POS
            else -> Kind.ONLINE_PURCHASE
        }
        val merchant = STC_MERCHANT_RE.find(body)?.groupValues?.get(1)?.trim()
        return ParsedSms(amount, Bank.STC, kind, merchant?.ifBlank { null })
    }

    // ── Amount extraction ──────────────────────────────────────────────
    //
    // AlRajhi writes amounts as "Amount:SAR 72.05" (currency first).
    // STC writes them as "Amount 57 SAR" or "Amount 111.75" (currency
    // after, sometimes missing).
    private fun extractAlRajhiAmount(body: String): Double? =
        AL_RAJHI_AMOUNT_RE.find(body)?.groupValues?.get(1)
            ?.replace(",", "")
            ?.toDoubleOrNull()

    private fun extractStcAmount(body: String): Double? =
        STC_AMOUNT_RE.find(body)?.groupValues?.get(1)
            ?.replace(",", "")
            ?.toDoubleOrNull()

    private fun String.containsIgnoreCase(needle: String) = contains(needle, ignoreCase = true)

    private fun String.matchesAlRajhi(): Boolean =
        contains("AlRajhi", ignoreCase = true) || contains("Al Rajhi", ignoreCase = true)

    private fun String.matchesStcBank(): Boolean =
        contains("STC Bank", ignoreCase = true) ||
            contains("STCBank", ignoreCase = true) ||
            equals("STC", ignoreCase = true)

    // Regex patterns are extracted to avoid re-compiling on every SMS.
    private val AL_RAJHI_AMOUNT_RE = Regex(
        """Amount\s*:\s*SAR\s*([\d,]+(?:\.\d+)?)""",
        RegexOption.IGNORE_CASE,
    )
    private val STC_AMOUNT_RE = Regex(
        """Amount\s+([\d,]+(?:\.\d+)?)(?:\s*SAR)?""",
        RegexOption.IGNORE_CASE,
    )
    private val AL_RAJHI_MERCHANT_RE = Regex(
        """At\s*:\s*([^\r\n]+)""",
        RegexOption.IGNORE_CASE,
    )
    private val STC_MERCHANT_RE = Regex(
        """From\s*:\s*([^\r\n]+)""",
        RegexOption.IGNORE_CASE,
    )
}

// The parser's return type — timestamp is filled in by the caller
// from the inbox row since the body's date is unreliable.
data class ParsedSms(
    val amountSar: Double,
    val bank: Transaction.Bank,
    val kind: Transaction.Kind,
    val merchant: String?,
)
