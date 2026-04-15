package net.omarss.omono.feature.spending

import io.kotest.matchers.nulls.shouldBeNull
import io.kotest.matchers.nulls.shouldNotBeNull
import io.kotest.matchers.shouldBe
import org.junit.Test

class SmsParserTest {

    // ── AlRajhi: capture ────────────────────────────────────────────────

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
        parsed.amountSar shouldBe 72.05
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
        parsed.amountSar shouldBe 15.0
        parsed.merchant shouldBe "Java Time"
    }

    @Test
    fun `alrajhi biller payment is captured`() {
        val body = """
            Amount:SAR 1000
            Biller:207
            Service:STC PAY
            Bill:61409921865
            26/4/9 20:47
        """.trimIndent()
        val parsed = SmsParser.parse("AlRajhiBank", body)
        parsed.shouldNotBeNull()
        parsed.amountSar shouldBe 1000.0
        parsed.kind shouldBe Transaction.Kind.BILLER
    }

    // ── AlRajhi: reject ─────────────────────────────────────────────────

    @Test
    fun `alrajhi otp is ignored`() {
        val body = "OTP Code:7665\nReason:Selling gold - Mobile App"
        SmsParser.parse("AlRajhiBank", body).shouldBeNull()
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
    fun `alrajhi declined inactive card is ignored`() {
        val body = """
            Transaction Declined: Inactive Card
            Transaction: Online Purchase
            Card: 0110
            Amount: USD 1
            Date: 11/4/26 20:10
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

    // ── STC Bank: capture ───────────────────────────────────────────────

    @Test
    fun `stc online purchase with SAR suffix is captured`() {
        val body = """
            Online Purchase Transaction
            Amount 57 SAR
            From: Jahez
             Card: *6066
            Date 11/04/26 20:21
        """.trimIndent()
        val parsed = SmsParser.parse("STC Bank", body)
        parsed.shouldNotBeNull()
        parsed.amountSar shouldBe 57.0
        parsed.bank shouldBe Transaction.Bank.STC
        parsed.kind shouldBe Transaction.Kind.ONLINE_PURCHASE
        parsed.merchant shouldBe "Jahez"
    }

    @Test
    fun `stc online purchase with decimal and no SAR suffix is captured`() {
        val body = """
            Online Purchase Transaction
            Amount 111.75
            From: Ninja Retail Company
             Card: *******9928
            Date 10/04/2026
        """.trimIndent()
        val parsed = SmsParser.parse("STC Bank", body)
        parsed.shouldNotBeNull()
        parsed.amountSar shouldBe 111.75
        parsed.merchant shouldBe "Ninja Retail Company"
    }

    @Test
    fun `stc online purchase masked card is still parsed`() {
        val body = """
            Online Purchase Transaction
            Amount 104 SAR
            From: MF(Tur
             Card: *6066
            Date 11/04/26 21:05
        """.trimIndent()
        val parsed = SmsParser.parse("STCBank", body)
        parsed.shouldNotBeNull()
        parsed.amountSar shouldBe 104.0
    }

    // ── STC Bank: reject ────────────────────────────────────────────────

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
    fun `stc declined is ignored`() {
        val body = "The transaction is not allowed. You can change the card setting through the app."
        SmsParser.parse("STC Bank", body).shouldBeNull()
    }

    // ── Unknown senders ────────────────────────────────────────────────

    @Test
    fun `unknown sender is ignored`() {
        val body = "PoS Amount:SAR 50 At:test"
        SmsParser.parse("RandomBank", body).shouldBeNull()
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
    fun `isKnownSender matches stc variants`() {
        SmsParser.isKnownSender("STC Bank") shouldBe true
        SmsParser.isKnownSender("STCBank") shouldBe true
    }
}
