package net.omarss.omono.core.notification

import android.app.Notification
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
    fun `buildOngoing produces an ongoing notification with each line`() {
        controller.ensureChannel(context)

        val notification = controller.buildOngoing(
            context = context,
            title = "Omono",
            subText = "Tracking",
            bodyLines = listOf("12.3 km/h", "Today SAR 45 · Month SAR 1,234"),
            contentIntent = null,
        )

        // FLAG_ONGOING_EVENT (2) should be set because the controller
        // marks the notification as ongoing.
        val isOngoing = notification.flags and Notification.FLAG_ONGOING_EVENT != 0
        isOngoing shouldBe true

        // Collapsed content text shows the first (most important) line.
        val collapsed = notification.extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()
        collapsed shouldBe "12.3 km/h"

        // SubText sits next to the app name in the header.
        val sub = notification.extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString()
        sub shouldBe "Tracking"

        // InboxStyle stores the expanded lines in EXTRA_TEXT_LINES.
        val lines = notification.extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)
            ?.map { it.toString() }
        lines shouldBe listOf("12.3 km/h", "Today SAR 45 · Month SAR 1,234")
    }

    @Test
    fun `buildOngoing handles empty body with placeholder`() {
        controller.ensureChannel(context)

        val notification = controller.buildOngoing(
            context = context,
            title = "Omono",
            subText = null,
            bodyLines = emptyList(),
            contentIntent = null,
        )

        val lines = notification.extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)
            ?.map { it.toString() }
        lines shouldBe listOf("Starting…")
    }

    @Test
    fun `buildOngoing uses the brand color`() {
        controller.ensureChannel(context)

        val notification = controller.buildOngoing(
            context = context,
            title = "Omono",
            subText = null,
            bodyLines = listOf("42.5 km/h"),
            contentIntent = null,
        )

        notification.color shouldBe android.graphics.Color.parseColor("#2563EB")
    }
}
