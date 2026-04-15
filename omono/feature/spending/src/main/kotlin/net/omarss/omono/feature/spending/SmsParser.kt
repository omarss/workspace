package net.omarss.omono.feature.spending

import net.omarss.omono.feature.spending.Transaction.Bank
import net.omarss.omono.feature.spending.Transaction.Kind

// Pure-Kotlin parser for bank transaction SMSes. Returns null for any
// message we don't want to track — OTPs, declines, own-account
// transfers, incoming credits, gold selling, and anything from an
// unknown sender. Timestamp is not parsed from the body; callers
// should pair the return value with the SMS inbox row's DATE column.
//
// Kinds are split into consumer purchases (POS / ONLINE_PURCHASE /
// BILLER / CASH_WITHDRAWAL / CREDIT_CARD_PAYMENT / GOVT_PAYMENT) and
// outgoing TRANSFER_OUT. Callers aggregate the two separately so the
// "spending" headline doesn't balloon when the user sends a remittance.
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
    // What we capture (with the first-line keyword that identifies each):
    //   "PoS"                    → Kind.POS
    //   "Bill Payment" (Biller:) → Kind.BILLER
    //   "MOI Payments"           → Kind.GOVT_PAYMENT
    //   "Credit Card:Payment"    → Kind.CREDIT_CARD_PAYMENT
    //   "Withdrawal:ATM"         → Kind.CASH_WITHDRAWAL
    //   "International Transfer" → Kind.TRANSFER_OUT (money to someone else)
    //
    // What we reject outright:
    //   OTP Code / One Time Password (auth)
    //   Transaction Declined / Notification : Declined (failed)
    //   Selling Gold (income)
    //   Debit Internal Transfer (own-account)
    //   Transfer Between Your Accounts (own-account)
    //   Rajhi Transfer (OTP-like, and duplicated by other messages)
    //   Credit Transfer Local (incoming credit — salary / deposit)
    //   Credit Card:transfer (duplicate of Credit Card:Payment)
    //   Deposit:* (incoming)
    //   Dear (Customer|customer) (marketing)
    //   Your card ... MadaPay (admin, no amount)
    //
    // Spending messages can report amount as "Amount:SAR X" or
    // "Amount:SR X" (rarer) — both honoured by the amount regex.
    private fun parseAlRajhi(body: String): ParsedSms? {
        // Hard rejects — these short-circuit before any keyword lookup
        // so a body that also happens to contain "PoS" inside a decline
        // doesn't accidentally get captured.
        if (body.containsIgnoreCase("OTP Code")) return null
        if (body.containsIgnoreCase("One Time Password")) return null
        if (body.containsIgnoreCase("Declined")) return null
        if (body.containsIgnoreCase("Selling Gold")) return null
        if (body.containsIgnoreCase("Debit Internal Transfer")) return null
        if (body.containsIgnoreCase("Transfer Between Your Accounts")) return null
        if (body.containsIgnoreCase("Rajhi Transfer")) return null
        if (body.containsIgnoreCase("Credit Transfer")) return null
        if (body.containsIgnoreCase("Credit Card:transfer")) return null
        if (body.containsIgnoreCase("Deposit:")) return null
        if (body.containsIgnoreCase("Dear customer") || body.containsIgnoreCase("Dear Customer")) return null
        if (body.containsIgnoreCase("Your card") && body.containsIgnoreCase("MadaPay")) return null
        if (body.containsIgnoreCase("verification code")) return null

        val amount = extractAlRajhiAmount(body) ?: return null

        // Detection order matters — more specific shapes first. "PoS"
        // is a 3-char needle so it goes last to avoid matching "Debit
        // PoS ..." style text elsewhere.
        val kind = when {
            body.containsIgnoreCase("MOI Payments") -> Kind.GOVT_PAYMENT
            body.containsIgnoreCase("Credit Card:Payment") -> Kind.CREDIT_CARD_PAYMENT
            body.containsIgnoreCase("Withdrawal:ATM") -> Kind.CASH_WITHDRAWAL
            body.containsIgnoreCase("International Transfer") -> Kind.TRANSFER_OUT
            body.contains("Biller:", ignoreCase = true) -> Kind.BILLER
            body.containsIgnoreCase("Online Purchase") -> Kind.ONLINE_PURCHASE
            body.containsIgnoreCase("PoS") -> Kind.POS
            else -> return null
        }

        val merchant = AL_RAJHI_MERCHANT_RE.find(body)?.groupValues?.get(1)?.trim()
            ?: AL_RAJHI_PLACE_RE.find(body)?.groupValues?.get(1)?.trim()
            ?: AL_RAJHI_SERVICE_RE.find(body)?.groupValues?.get(1)?.trim()
            ?: AL_RAJHI_TO_RE.find(body)?.groupValues?.get(1)?.trim()
        return ParsedSms(amount, Bank.AL_RAJHI, kind, merchant?.ifBlank { null })
    }

    // ── STC Bank ────────────────────────────────────────────────────────
    //
    // Shapes we capture:
    //   "Online Purchase Transaction Amount 57 SAR From: Jahez ..."
    //   "Online Purchase Transaction Amount 111.75 From: Ninja Retail ..."
    //   "Local Purchase Card: *6066; mada Pay Amount: 13 SAR At: ucoffe ..."
    //
    // Shapes we skip:
    //   OTPs (both "… is your OTP" and "Please use one time password")
    //   "The transaction is not allowed…"
    private fun parseStcBank(body: String): ParsedSms? {
        if (body.containsIgnoreCase("is your OTP")) return null
        if (body.containsIgnoreCase("one time password")) return null
        if (body.containsIgnoreCase("not allowed")) return null
        if (body.containsIgnoreCase("Do not share")) return null

        val kind = when {
            body.containsIgnoreCase("Online Purchase Transaction") -> Kind.ONLINE_PURCHASE
            body.containsIgnoreCase("POS Transaction") -> Kind.POS
            body.containsIgnoreCase("Local Purchase") -> Kind.POS
            else -> return null
        }

        val amount = extractStcAmount(body) ?: return null
        val merchant = STC_FROM_RE.find(body)?.groupValues?.get(1)?.trim()
            ?: STC_AT_RE.find(body)?.groupValues?.get(1)?.trim()
        return ParsedSms(amount, Bank.STC, kind, merchant?.ifBlank { null })
    }

    // ── Amount extraction ──────────────────────────────────────────────
    //
    // AlRajhi: "Amount:SAR 72.05" or "Amount:SR 800" (optional space
    // around colon; currency is SAR or SR; decimals optional).
    //
    // STC: "Amount 57 SAR", "Amount 111.75", or "Amount: 13 SAR".
    // The colon is optional; the SAR suffix is optional.
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

    // Tightened: only match "STC Bank" / "STCBank" — the older
    // `equals("STC")` clause was catching the telecom provider's
    // Arabic VAT notifications (sender address literally "stc").
    private fun String.matchesStcBank(): Boolean =
        contains("STC Bank", ignoreCase = true) ||
            contains("STCBank", ignoreCase = true)

    private val AL_RAJHI_AMOUNT_RE = Regex(
        """Amount\s*:\s*(?:SAR|SR)\s+([\d,]+(?:\.\d+)?)""",
        RegexOption.IGNORE_CASE,
    )
    private val STC_AMOUNT_RE = Regex(
        """Amount\s*:?\s+([\d,]+(?:\.\d+)?)\s*(?:SAR)?""",
        RegexOption.IGNORE_CASE,
    )
    private val AL_RAJHI_MERCHANT_RE = Regex(
        """At\s*:\s*([^\r\n]+)""",
        RegexOption.IGNORE_CASE,
    )

    // Additional merchant-like fields on AlRajhi shapes that don't use
    // "At:" — MOI Payments uses "Service:", Withdrawal:ATM uses
    // "Place:", International Transfer uses "To:".
    private val AL_RAJHI_PLACE_RE = Regex(
        """Place\s*:\s*([^\r\n]+)""",
        RegexOption.IGNORE_CASE,
    )
    private val AL_RAJHI_SERVICE_RE = Regex(
        """Service\s*:\s*([^\r\n]+)""",
        RegexOption.IGNORE_CASE,
    )
    private val AL_RAJHI_TO_RE = Regex(
        """To\s*:\s*(?!\d+\s*$)([^\r\n]+)""",
        RegexOption.IGNORE_CASE,
    )

    private val STC_FROM_RE = Regex(
        """From\s*:\s*([^\r\n]+)""",
        RegexOption.IGNORE_CASE,
    )
    private val STC_AT_RE = Regex(
        """At\s*:\s*([^\r\n]+)""",
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
