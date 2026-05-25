package net.omarss.omono.feature.spending

import io.kotest.matchers.shouldBe
import io.kotest.matchers.shouldNotBe
import org.junit.Test

class RecipientNormalizerTest {

    @Test
    fun `same person across transliteration variants normalises identically`() {
        // SHABAAN / SHAABAAN / SHAABAN — three Latinisations of شعبان
        // that the Saudi bank emits unpredictably for the same person.
        val a = recipientKey("OMAR SHABAAN")
        recipientKey("OMAR SHAABAAN") shouldBe a
        recipientKey("OMAR SHAABAN") shouldBe a
    }

    @Test
    fun `mohmmad and muhammad collapse to same skeleton`() {
        val a = recipientKey("MOHMMAD OSEMI")
        recipientKey("MUHAMMAD OSEMI") shouldBe a
        recipientKey("MOHAMMAD OSEMI") shouldBe a
        recipientKey("Mohmmad Osemi") shouldBe a
    }

    @Test
    fun `khaled and khalid collapse to same skeleton`() {
        recipientKey("KHALED SHABAAN") shouldBe recipientKey("KHALID SHAABAAN")
    }

    @Test
    fun `case and whitespace fold`() {
        recipientKey("  AJMAL   ANWAR  ") shouldBe recipientKey("ajmal anwar")
    }

    @Test
    fun `distinct people do not collide`() {
        // Different consonant skeletons — must not merge.
        recipientKey("OMAR SHABAAN") shouldNotBe recipientKey("OMAR OSEMI")
        recipientKey("KHALED SHABAAN") shouldNotBe recipientKey("AJMAL ANWAR")
    }

    @Test
    fun `y is treated as consonant — alsayed and alsaid differ`() {
        // Documented limitation: y is kept as a consonant so MAYO and
        // similar don't collapse to a single letter. The tradeoff is
        // that ALSAYED and ALSAID don't merge — acceptable false split.
        recipientKey("ALSAYED SHABAAN") shouldNotBe recipientKey("ALSAID SHABAAN")
    }

    @Test
    fun `arabic script names match each other literally`() {
        val arabic = "شركة القمة الهامة للتقنية المالية"
        recipientKey(arabic) shouldBe recipientKey(arabic)
        // Whitespace inside Arabic still folds.
        recipientKey("  $arabic  ") shouldBe recipientKey(arabic)
    }

    @Test
    fun `arabic and latin names never collide`() {
        recipientKey("شركة الهامة") shouldNotBe recipientKey("OMAR SHABAAN")
    }

    @Test
    fun `punctuation and digits drop`() {
        recipientKey("OMAR S. SHABAAN") shouldBe recipientKey("OMAR S SHABAAN")
        recipientKey("OMAR-SHABAAN") shouldBe recipientKey("OMAR SHABAAN")
        recipientKey("OMAR SHABAAN 2") shouldBe recipientKey("OMAR SHABAAN")
    }

    @Test
    fun `empty and blank return empty`() {
        recipientKey("") shouldBe ""
        recipientKey("   ") shouldBe ""
    }
}
