package net.omarss.omono.feature.spending

// One parsed financial event from a bank SMS.
// Amount is always in Saudi Riyals (SAR); both supported banks report
// SAR natively so no currency conversion is needed.
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
) {
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

        /** Payment toward a credit card balance. */
        CREDIT_CARD_PAYMENT,

        /** Government / MOI payment (traffic fines, passports, etc.). */
        GOVT_PAYMENT,

        /**
         * Money transferred to another person or entity. Tracked
         * separately from purchases so salary remittances don't
         * inflate the "spending" headline.
         */
        TRANSFER_OUT,
    }
}

// Everything except outgoing transfers counts toward the purchase total.
val Transaction.Kind.isPurchase: Boolean
    get() = this != Transaction.Kind.TRANSFER_OUT
