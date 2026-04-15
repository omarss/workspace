package net.omarss.omono.feature.spending

// One parsed consumer spending transaction from a bank SMS.
// Amount is always in Saudi Riyals (SAR); both supported banks report
// SAR natively so no currency conversion is needed.
//
// timestampMillis is sourced from the Android SMS inbox row
// (Telephony.Sms.DATE) rather than any date embedded in the body —
// inbox dates are in epoch millis, already timezone-normalised, and
// never ambiguous between Gregorian and Hijri calendars.
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
    }
}
