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
        // STC Pay top-ups show up as Bill Payment / Biller:207 /
        // Service:STC PAY. They're the user moving money between
        // their own accounts, not spending — reject outright.
        if (body.containsIgnoreCase("STC PAY")) return null

        val currencyPair = extractAlRajhiAmount(body) ?: return null
        val (originalAmount, rawCurrency) = currencyPair
        // Parser stays pure — the repository is responsible for the
        // SAR conversion via an injected CurrencyConverter that can
        // use live FX rates. We still canonicalise SR → SAR here so
        // downstream code only deals with one spelling.
        val originalCurrency = canonicalizeCurrency(rawCurrency)

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
        return ParsedSms(
            bank = Bank.AL_RAJHI,
            kind = kind,
            merchant = merchant?.ifBlank { null },
            originalAmount = originalAmount,
            originalCurrency = originalCurrency,
        )
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
            // "VISA Purchase" is STC's non-mada card shape. The body
            // looks like "VISA Purchase / Via: *6638 / Amount: X / From: Y"
            // so downstream regexes (Amount, From:) work as-is.
            // Classify by whether the From/At hint looks online or
            // physical — in practice VISA Purchase through an app or
            // subscription service is always "online".
            body.containsIgnoreCase("VISA Purchase") -> Kind.ONLINE_PURCHASE
            else -> return null
        }

        val extracted = extractStcAmount(body) ?: return null
        val (originalAmount, rawCurrency) = extracted
        val originalCurrency = canonicalizeCurrency(rawCurrency)
        val merchant = STC_FROM_RE.find(body)?.groupValues?.get(1)?.trim()
            ?: STC_AT_RE.find(body)?.groupValues?.get(1)?.trim()
        return ParsedSms(
            bank = Bank.STC,
            kind = kind,
            merchant = merchant?.ifBlank { null },
            originalAmount = originalAmount,
            originalCurrency = originalCurrency,
        )
    }

    // "SR" is an Al Rajhi shorthand for SAR; everything else passes
    // through uppercased so the downstream converter can key off a
    // canonical ISO-4217 string.
    private fun canonicalizeCurrency(currency: String): String {
        val upper = currency.uppercase()
        return if (upper == "SR") "SAR" else upper
    }

    // ── Amount extraction ──────────────────────────────────────────────
    //
    // AlRajhi: "Amount:SAR 72.05", "Amount:SR 800", "Amount: USD 13.31".
    // Currency precedes the number; SAR/SR collapse to SAR.
    //
    // STC: "Amount 57 SAR", "Amount 230 USD", "Amount: 13 SAR",
    // "Amount 111.75" (no suffix defaults to SAR). Currency follows
    // the number.
    //
    // Both return the numeric value paired with the raw currency code,
    // so the caller (parseAlRajhi / parseStcBank) decides how to
    // convert into SAR and what to store as the "original" amount.
    private fun extractAlRajhiAmount(body: String): Pair<Double, String>? {
        val match = AL_RAJHI_AMOUNT_RE.find(body) ?: return null
        val currency = match.groupValues[1]
        val amount = match.groupValues[2].replace(",", "").toDoubleOrNull() ?: return null
        return amount to currency
    }

    private fun extractStcAmount(body: String): Pair<Double, String>? {
        val match = STC_AMOUNT_RE.find(body) ?: return null
        val amount = match.groupValues[1].replace(",", "").toDoubleOrNull() ?: return null
        val currency = match.groupValues[2].ifBlank { "SAR" }
        return amount to currency
    }

    private fun String.containsIgnoreCase(needle: String) = contains(needle, ignoreCase = true)

    private fun String.matchesAlRajhi(): Boolean =
        contains("AlRajhi", ignoreCase = true) || contains("Al Rajhi", ignoreCase = true)

    // Tightened: only match "STC Bank" / "STCBank" — the older
    // `equals("STC")` clause was catching the telecom provider's
    // Arabic VAT notifications (sender address literally "stc").
    private fun String.matchesStcBank(): Boolean =
        contains("STC Bank", ignoreCase = true) ||
            contains("STCBank", ignoreCase = true)

    // AlRajhi shape: currency token precedes the number.
    //   group 1 = currency code (SAR | SR | USD | EUR | …)
    //   group 2 = numeric amount
    private val AL_RAJHI_AMOUNT_RE = Regex(
        """Amount\s*:\s*([A-Z]{2,4})\s+([\d,]+(?:\.\d+)?)""",
        RegexOption.IGNORE_CASE,
    )

    // STC shape: number first, optional currency suffix.
    //   group 1 = numeric amount
    //   group 2 = currency code (empty when the SMS omitted it — STC
    //              occasionally sends "Amount 111.75" with no suffix;
    //              callers default that to SAR).
    private val STC_AMOUNT_RE = Regex(
        """Amount\s*:?\s+([\d,]+(?:\.\d+)?)\s*([A-Z]{2,4})?""",
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
// from the inbox row, and the SAR conversion is done by the
// repository against a live-rate CurrencyConverter so the parser
// stays a pure function.
data class ParsedSms(
    val bank: Transaction.Bank,
    val kind: Transaction.Kind,
    val merchant: String?,
    val originalAmount: Double,
    val originalCurrency: String,
)
