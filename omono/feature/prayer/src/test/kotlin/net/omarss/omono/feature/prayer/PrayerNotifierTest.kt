package net.omarss.omono.feature.prayer

import android.Manifest
import android.app.Application
import android.app.NotificationManager
import android.content.Context
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class PrayerNotifierTest {
    private val context: Application = RuntimeEnvironment.getApplication()
    private val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

    @Test
    fun `denied permission prevents posting a prayer notification`() {
        shadowOf(context).denyPermissions(Manifest.permission.POST_NOTIFICATIONS)

        PrayerNotifier(context).notify(context, PrayerKind.Dhuhr, 0L)

        assertEquals(0, shadowOf(manager).allNotifications.size)
    }

    @Test
    fun `granted permission allows a prayer notification`() {
        shadowOf(context).grantPermissions(Manifest.permission.POST_NOTIFICATIONS)

        PrayerNotifier(context).notify(context, PrayerKind.Dhuhr, 0L)

        assertEquals(1, shadowOf(manager).allNotifications.size)
    }

    @Test
    @Config(sdk = [32])
    fun `older Android posts without the Android 13 permission`() {
        PrayerNotifier(context).notify(context, PrayerKind.Dhuhr, 0L)

        assertEquals(1, shadowOf(manager).allNotifications.size)
    }
}
