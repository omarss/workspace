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

        /**
         * Payment from the debit account toward a credit card balance
         * (an Al Rajhi card top-up). Not a purchase — see isPurchase.
         */
        CREDIT_CARD_PAYMENT,

        /** Government / MOI payment (traffic fines, passports, etc.). */
        GOVT_PAYMENT,

        /**
         * Money transferred to another person or entity. Tracked
         * separately from purchases so salary remittances don't
         * inflate the "spending" headline.
         */
        TRANSFER_OUT,

        /**
         * Refund / reversal posted back to the account. Subtracted
         * from the month's purchase total so the headline reflects
         * the net outflow, and surfaced in its own UI row so the
         * user can see where the money came back from.
         */
        REFUND,
    }
}

// True when the transaction drives the purchase total up. Everything
// else (refunds, transfers, credit-card balance top-ups) is tracked on
// its own ledger. Credit-card payments in particular look like "money
// out" but are actually an own-account move: the debit account pays
// the card, and the spending that earned the balance was already
// captured at the POS/online transaction via the card. Counting the
// payment as well would double-book the amount.
val Transaction.Kind.isPurchase: Boolean
    get() = this != Transaction.Kind.TRANSFER_OUT &&
        this != Transaction.Kind.REFUND &&
        this != Transaction.Kind.CREDIT_CARD_PAYMENT
