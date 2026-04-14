package net.omarss.omono.core.notification

import android.app.NotificationManager
import android.content.Context
import androidx.core.content.getSystemService
import androidx.test.core.app.ApplicationProvider
import io.kotest.matchers.shouldBe
import io.kotest.matchers.shouldNotBe
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class OmonoNotificationControllerTest {

    private val context: Context get() = ApplicationProvider.getApplicationContext()
    private val controller = OmonoNotificationController()

    @Test
    fun `ensureChannel registers the host channel`() {
        controller.ensureChannel(context)

        val manager = context.getSystemService<NotificationManager>()!!
        val channel = manager.getNotificationChannel(OmonoNotificationChannels.FEATURE_HOST_CHANNEL_ID)
        channel shouldNotBe null
        channel.importance shouldBe NotificationManager.IMPORTANCE_LOW
    }

    @Test
    fun `ensureChannel is idempotent`() {
        controller.ensureChannel(context)
        controller.ensureChannel(context)

        val manager = context.getSystemService<NotificationManager>()!!
        manager.notificationChannels
            .count { it.id == OmonoNotificationChannels.FEATURE_HOST_CHANNEL_ID } shouldBe 1
    }

    @Test
    fun `buildOngoing produces an ongoing notification with body lines`() {
        controller.ensureChannel(context)

        val notification = controller.buildOngoing(
            context = context,
            title = "Omono",
            bodyLines = listOf("12.3 km/h", "75 dB"),
            contentIntent = null,
        )

        // FLAG_ONGOING_EVENT (2) and FLAG_NO_CLEAR (32) should be set
        // because the controller marks the notification as ongoing.
        val isOngoing = notification.flags and android.app.Notification.FLAG_ONGOING_EVENT != 0
        isOngoing shouldBe true

        val body = notification.extras.getCharSequence(android.app.Notification.EXTRA_BIG_TEXT)?.toString()
        body shouldBe "12.3 km/h\n75 dB"
    }

    @Test
    fun `buildOngoing handles empty body with placeholder`() {
        controller.ensureChannel(context)

        val notification = controller.buildOngoing(
            context = context,
            title = "Omono",
            bodyLines = emptyList(),
            contentIntent = null,
        )

        val text = notification.extras.getCharSequence(android.app.Notification.EXTRA_TEXT)?.toString()
        text shouldBe "Starting…"
    }
}
