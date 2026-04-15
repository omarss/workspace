package net.omarss.omono.feature.selfupdate

import io.kotest.matchers.shouldBe
import org.junit.Test

class VersionTest {

    @Test
    fun `newer major is greater`() {
        (compareVersions("2.0.0", "1.9.9") > 0) shouldBe true
    }

    @Test
    fun `newer minor is greater`() {
        (compareVersions("0.10.0", "0.9.9") > 0) shouldBe true
    }

    @Test
    fun `newer patch is greater`() {
        (compareVersions("0.9.1", "0.9.0") > 0) shouldBe true
    }

    @Test
    fun `equal versions compare equal`() {
        compareVersions("1.2.3", "1.2.3") shouldBe 0
    }

    @Test
    fun `missing trailing components default to zero`() {
        compareVersions("1.2", "1.2.0") shouldBe 0
        (compareVersions("1.2.1", "1.2") > 0) shouldBe true
    }

    @Test
    fun `suffixes are stripped before comparison`() {
        compareVersions("1.2.3-rc1", "1.2.3") shouldBe 0
    }
}
