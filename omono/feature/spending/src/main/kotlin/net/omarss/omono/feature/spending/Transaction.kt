package net.omarss.omono.feature.spending

// One parsed financial event from a bank SMS.
//
// `amountSar` is always in Saudi Riyals and is the value used for all
// aggregation / budgeting. For foreign-currency transactions the
// parser pre-converts via CurrencyConverter and stores the original
// amount + currency alongside so the UI can surface the source value
// (e.g. "SAR 863 (USD 230)" for Claude subscriptions).
//
// timestampMillis is sourced from the Android SMS inbox row
// (Telephony.Sms.DATE) rather than any date embedded in the body —
// inbox dates are in epoch millis, already timezone-normalised, and
// never ambiguous between Gregorian and Hijri calendars.
//
// `kind` distinguishes consumer purchases (rolled into the headline
// "spending" totals) from outgoing transfers (shown separately so the
// user can see money-to-others without inflating the purchase total).
// See Kind.isPurchase.
data class Transaction(
    val amountSar: Double,
    val timestampMillis: Long,
    val bank: Bank,
    val kind: Kind,
    val merchant: String?,
    val originalAmount: Double = amountSar,
    val originalCurrency: String = "SAR",
    // True when the currency converter had no live / static rate for
    // this transaction's `originalCurrency`, so `amountSar` is an
    // equal-units fallback rather than a real SAR conversion. The
    // totals still add the fallback value (better under-count than
    // silent drop), but the Recent activity row can surface a badge
    // so the user knows the number isn't quite right.
    val fxFailed: Boolean = false,
) {
    val isForeignCurrency: Boolean
        get() = originalCurrency != "SAR"

    enum class Bank { AL_RAJHI, STC }

    enum class Kind {
        /** Physical card purchase (Point of Sale). */
        POS,

        /** Card-not-present online purchase. */
        ONLINE_PURCHASE,

        /** Biller payment — utilities, STC Pay top-up, etc. */
        BILLER,

        /** Cash pulled from an ATM — counted as spending. */
        CASH_WITHDRAWAL,

        /** Government / MOI payment (traffic fines, passports, etc.). */
        GOVT_PAYMENT,

        /**
         * Money transferred to another person or entity. Tracked
         * separately from purchases so salary remittances don't
         * inflate the "spending" headline.
         */
        TRANSFER_OUT,

        /**
         * Money credited into the account from another party — bank
         * "Credit Transfer" (incoming wires / salaries / P2P), bank
         * deposits (monthly profit, dividends, etc.). Book-kept on
         * the same Transfers ledger as TRANSFER_OUT so the user can
         * see inflows and outflows side by side, but direction is
         * carried explicitly so the UI can distinguish them.
         */
        TRANSFER_IN,

        /**
         * Refund / reversal posted back to the account. Subtracted
         * from the month's purchase total so the headline reflects
         * the net outflow, and surfaced in its own UI row so the
         * user can see where the money came back from.
         */
        REFUND,
    }
}

// True when the transaction drives the purchase total up. Transfers
// (money to/from another person) and refunds (money coming back) are
// tracked on their own ledgers and intentionally excluded.
val Transaction.Kind.isPurchase: Boolean
    get() = this != Transaction.Kind.TRANSFER_OUT &&
        this != Transaction.Kind.TRANSFER_IN &&
        this != Transaction.Kind.REFUND

// True when the transaction affects the Transfers card — inflow and
// outflow are both rendered there but styled differently.
val Transaction.Kind.isTransfer: Boolean
    get() = this == Transaction.Kind.TRANSFER_OUT || this == Transaction.Kind.TRANSFER_IN
