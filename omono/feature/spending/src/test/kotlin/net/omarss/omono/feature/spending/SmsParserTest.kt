package net.omarss.omono.feature.spending

import io.kotest.matchers.nulls.shouldBeNull
import io.kotest.matchers.nulls.shouldNotBeNull
import io.kotest.matchers.shouldBe
import org.junit.Test

class SmsParserTest {

    // ── AlRajhi: purchases ─────────────────────────────────────────────

    @Test
    fun `alrajhi pos with mada pay is captured`() {
        val body = """
            PoS
            By:8025;mada-mada Pay
            Amount:SAR 72.05
            At:ALDREES 4
            10/4/26 12:49
        """.trimIndent()
        val parsed = SmsParser.parse("AlRajhiBank", body)
        parsed.shouldNotBeNull()
        parsed.originalAmount shouldBe 72.05
        parsed.bank shouldBe Transaction.Bank.AL_RAJHI
        parsed.kind shouldBe Transaction.Kind.POS
        parsed.merchant shouldBe "ALDREES 4"
    }

    @Test
    fun `alrajhi pos with integer amount is captured`() {
        val body = """
            PoS
            By:8025;mada-mada Pay
            Amount:SAR 15
            At:Java Time
            12/4/26 09:50
        """.trimIndent()
        val parsed = SmsParser.parse("AlRajhiBank", body)
        parsed.shouldNotBeNull()
        parsed.originalAmount shouldBe 15.0
        parsed.merchant shouldBe "Java Time"
    }

    @Test
    fun `alrajhi stc pay bill payment is ignored as own account transfer`() {
        // Regression: STC Pay top-ups previously counted as BILLER
        // purchases. They're the user moving money between their own
        // accounts, so they should be rejected outright.
        val body = """
            Bill Payment
            From:7131
            Amount:SAR 1000
            Biller:207
            Service:STC PAY
            Bill:61409921865
            26/4/9 20:47
        """.trimIndent()
        SmsParser.parse("AlRajhiBank", body).shouldBeNull()
    }

    @Test
    fun `alrajhi stc pay bill payment with SR currency is ignored`() {
        val body = """
            Bill Payment
            From:7131
            Amount:SR 800
            Biller:207
            Service:STC PAY
            Bill:61409921865
            26/4/11 07:06
        """.trimIndent()
        SmsParser.parse("AlRajhiBank", body).shouldBeNull()
    }

    @Test
    fun `alrajhi non stc pay bill payment is still captured`() {
        val body = """
            Bill Payment
            From:7131
            Amount:SAR 500
            Biller:310
            Service:Saudi Electricity
            Bill:99887766
            26/4/9 20:47
        """.trimIndent()
        val parsed = SmsParser.parse("AlRajhiBank", body)
        parsed.shouldNotBeNull()
        parsed.originalAmount shouldBe 500.0
        parsed.kind shouldBe Transaction.Kind.BILLER
    }

    @Test
    fun `alrajhi moi payment is captured as govt`() {
        val body = """
            MOI Payments
            From:7131
            Amount:SAR 338
            Provider:Traffic Violations
            Service:Traffic Violations Payment
            26/2/27 14:29
        """.trimIndent()
        val parsed = SmsParser.parse("AlRajhiBank", body)
        parsed.shouldNotBeNull()
        parsed.originalAmount shouldBe 338.0
        parsed.kind shouldBe Transaction.Kind.GOVT_PAYMENT
    }

    @Test
    fun `alrajhi credit card payment is captured`() {
        val body = """
            Credit Card:Payment
            Card:Visa 4527
            Amount:SAR 200
            Balance:220.1 SAR
            18/3/26 1:49
        """.trimIndent()
        val parsed = SmsParser.parse("AlRajhiBank", body)
        parsed.shouldNotBeNull()
        parsed.originalAmount shouldBe 200.0
        parsed.kind shouldBe Transaction.Kind.CREDIT_CARD_PAYMENT
    }

    @Test
    fun `alrajhi atm withdrawal is captured as cash`() {
        val body = """
            Withdrawal:ATM
            By:8025;mada
            Amount:SAR 450
            Place:AL DEREHMIYA
            21/3/26 13:53
        """.trimIndent()
        val parsed = SmsParser.parse("AlRajhiBank", body)
        parsed.shouldNotBeNull()
        parsed.originalAmount shouldBe 450.0
        parsed.kind shouldBe Transaction.Kind.CASH_WITHDRAWAL
        parsed.merchant shouldBe "AL DEREHMIYA"
    }

    // ── AlRajhi: transfers (separate from purchases) ───────────────────

    @Test
    fun `alrajhi international transfer is captured as transfer_out`() {
        val body = """
            International Transfer
            Country:Morocco
            From:7131
            To:Souad Bouaqa
            Amount:SAR 4969.50
            26/3/29 23:21
        """.trimIndent()
        val parsed = SmsParser.parse("AlRajhiBank", body)
        parsed.shouldNotBeNull()
        parsed.originalAmount shouldBe 4969.50
        parsed.kind shouldBe Transaction.Kind.TRANSFER_OUT
    }

    @Test
    fun `transfer_out kind is NOT a purchase`() {
        Transaction.Kind.TRANSFER_OUT.isPurchase shouldBe false
        Transaction.Kind.POS.isPurchase shouldBe true
        Transaction.Kind.ONLINE_PURCHASE.isPurchase shouldBe true
        Transaction.Kind.BILLER.isPurchase shouldBe true
        Transaction.Kind.CASH_WITHDRAWAL.isPurchase shouldBe true
        Transaction.Kind.CREDIT_CARD_PAYMENT.isPurchase shouldBe true
        Transaction.Kind.GOVT_PAYMENT.isPurchase shouldBe true
    }

    // ── AlRajhi: rejects ───────────────────────────────────────────────

    @Test
    fun `alrajhi otp is ignored`() {
        SmsParser.parse("AlRajhiBank", "OTP Code:7665\nReason:Selling gold - Mobile App").shouldBeNull()
    }

    @Test
    fun `alrajhi declined online purchase is ignored`() {
        val body = """
            Transaction Declined: Insufficient funds.
            Transaction: Online Purchase
            Card: 4527
            Amount: SAR 179
            At: Google No
            Date: 5/4/26 19:15
        """.trimIndent()
        SmsParser.parse("AlRajhiBank", body).shouldBeNull()
    }

    @Test
    fun `alrajhi notification declined pos is ignored`() {
        val body = """
            Notification : Declined due to insufficient fund
            Transaction : PoS
            Card: 4527
            Amount : SAR 39.99
            Merchant : APPLE.COM
            Date : 20/2/26 00:50
        """.trimIndent()
        SmsParser.parse("AlRajhiBank", body).shouldBeNull()
    }

    @Test
    fun `alrajhi gold selling is ignored`() {
        val body = """
            Selling Gold
            Amount:SAR 11284.24
            To:5344
            13/4/26 09:18
        """.trimIndent()
        SmsParser.parse("AlRajhiBank", body).shouldBeNull()
    }

    @Test
    fun `alrajhi internal transfer is ignored`() {
        val body = """
            Debit Internal Transfer
            From:7131
            Amount:SAR 3000
        """.trimIndent()
        SmsParser.parse("AlRajhiBank", body).shouldBeNull()
    }

    @Test
    fun `alrajhi transfer between your accounts is ignored`() {
        val body = """
            Transfer Between Your Accounts
            Amount: SAR 15000
            To: 7131
            26/3/15 22:39
        """.trimIndent()
        SmsParser.parse("AlRajhiBank", body).shouldBeNull()
    }

    @Test
    fun `alrajhi credit transfer local is ignored as incoming`() {
        val body = """
            Credit Transfer Local
            Via:ANB
            Amount:SAR 30000
            To:7131
            From:شركة القمة الهامة للتقنية المالية
            From:0019
            26/3/29 09:01
        """.trimIndent()
        SmsParser.parse("AlRajhiBank", body).shouldBeNull()
    }

    @Test
    fun `alrajhi deposit is ignored as incoming`() {
        val body = """
            Deposit:Saving Account Monthly Profit
            Amount:SAR 1.11
            To:0758
            1/3/26 07:21
        """.trimIndent()
        SmsParser.parse("AlRajhiBank", body).shouldBeNull()
    }

    @Test
    fun `alrajhi credit card transfer is ignored as duplicate`() {
        val body = """
            Credit Card:transfer
            From card:4527;Visa
            To Account:7131
            Amount:SAR 220.10
            26/3/18 01:51
        """.trimIndent()
        SmsParser.parse("AlRajhiBank", body).shouldBeNull()
    }

    @Test
    fun `alrajhi dear customer marketing is ignored`() {
        val body = """
            Dear Customer,
            You have a request to add your card ending with 8025 to MadaPay.
        """.trimIndent()
        SmsParser.parse("AlRajhiBank", body).shouldBeNull()
    }

    @Test
    fun `alrajhi mada pay admin is ignored`() {
        val body = "Your card 8025 is successfully added to MadaPay following your request."
        SmsParser.parse("AlRajhiBank", body).shouldBeNull()
    }

    // ── STC Bank: purchases ─────────────────────────────────────────────

    @Test
    fun `stc online purchase with amount on same line as header is captured`() {
        // Real export: "Online Purchase Transaction Amount 57 SAR" is one line.
        val body = """
            Online Purchase Transaction Amount 57 SAR
            From: Jahez
             Card: *6066
            Date 11/04/26 20:21
        """.trimIndent()
        val parsed = SmsParser.parse("STC Bank", body)
        parsed.shouldNotBeNull()
        parsed.originalAmount shouldBe 57.0
        parsed.bank shouldBe Transaction.Bank.STC
        parsed.kind shouldBe Transaction.Kind.ONLINE_PURCHASE
        parsed.merchant shouldBe "Jahez"
    }

    @Test
    fun `stc online purchase with decimal and no SAR suffix is captured`() {
        val body = """
            Online Purchase Transaction Amount 111.75
            From: Ninja Retail Company
             Card: *******9928
            Date 10/04/2026
        """.trimIndent()
        val parsed = SmsParser.parse("STC Bank", body)
        parsed.shouldNotBeNull()
        parsed.originalAmount shouldBe 111.75
        parsed.merchant shouldBe "Ninja Retail Company"
    }

    @Test
    fun `stc online purchase in USD is converted to SAR at 3_75`() {
        // Real export: "Online Purchase Transaction Amount 230 USD / From: CLAUDE"
        // 230 × 3.75 = 862.5 SAR. Both the converted value and the
        // original amount should be preserved.
        val body = """
            Online Purchase Transaction Amount 230 USD
            From: CLAUDE
             Card: *6638
            Date 01/04/26 15:40
        """.trimIndent()
        val parsed = SmsParser.parse("STC Bank", body)
        parsed.shouldNotBeNull()
        parsed.originalAmount shouldBe 230.0
        parsed.originalCurrency shouldBe "USD"
        parsed.kind shouldBe Transaction.Kind.ONLINE_PURCHASE
        parsed.merchant shouldBe "CLAUDE"
    }

    @Test
    fun `stc online purchase in USD with decimal is converted`() {
        val body = """
            Online Purchase Transaction Amount 13.31 USD
            From: MIRON ENTERPRISES
             Card: *6638
            Date 27/02/26 22:43
        """.trimIndent()
        val parsed = SmsParser.parse("STC Bank", body)
        parsed.shouldNotBeNull()
        parsed.originalAmount shouldBe 13.31
        parsed.originalCurrency shouldBe "USD"
    }

    @Test
    fun `stc local purchase with colon amount is captured as POS`() {
        // Real export shape: "Amount: 13 SAR" with colon and SAR suffix,
        // merchant under "At:" not "From:".
        val body = """
            Local Purchase
            Card: *6066; mada Pay (Atheer)
            Amount: 13 SAR
            At: ucoffe
            Date: 26/02/26 18:28
        """.trimIndent()
        val parsed = SmsParser.parse("STC Bank", body)
        parsed.shouldNotBeNull()
        parsed.originalAmount shouldBe 13.0
        parsed.kind shouldBe Transaction.Kind.POS
        parsed.merchant shouldBe "ucoffe"
    }

    // ── STC Bank: rejects ──────────────────────────────────────────────

    @Test
    fun `stc otp is ignored`() {
        val body = """
            7918 is your OTP
            For:MyFatoorah
            Amount: SAR 104.0
            *Do not share the code
        """.trimIndent()
        SmsParser.parse("STC Bank", body).shouldBeNull()
    }

    @Test
    fun `stc one time password prompt is ignored`() {
        val body = """
            Please use one time password 5179 for online payment
            Transaction Amount 72.07 SAR
            For Ninja Food Company
            Date 04/04/2026 and Time 11:18
        """.trimIndent()
        SmsParser.parse("STC Bank", body).shouldBeNull()
    }

    @Test
    fun `stc not allowed is ignored`() {
        SmsParser.parse(
            "STC Bank",
            "The transaction is not allowed. You can change the card setting through the app.",
        ).shouldBeNull()
    }

    // ── Unknown senders ────────────────────────────────────────────────

    @Test
    fun `unknown sender is ignored`() {
        SmsParser.parse("RandomBank", "PoS Amount:SAR 50 At:test").shouldBeNull()
    }

    @Test
    fun `null sender is ignored`() {
        SmsParser.parse(null, "anything").shouldBeNull()
    }

    // ── Sender matcher ────────────────────────────────────────────────

    @Test
    fun `isKnownSender matches alrajhi variants`() {
        SmsParser.isKnownSender("AlRajhiBank") shouldBe true
        SmsParser.isKnownSender("Al Rajhi") shouldBe true
    }

    @Test
    fun `isKnownSender matches stc bank variants`() {
        SmsParser.isKnownSender("STC Bank") shouldBe true
        SmsParser.isKnownSender("STCBank") shouldBe true
    }

    @Test
    fun `isKnownSender rejects stc telecom sender`() {
        // Regression: previously "equals('STC')" was catching the
        // telecom provider's Arabic VAT notifications.
        SmsParser.isKnownSender("stc") shouldBe false
        SmsParser.isKnownSender("STC") shouldBe false
    }
}
