package net.omarss.omono.feature.prayer

import android.app.Application
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.MediaPlayer
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowMediaPlayer

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class AthanPlayerTest {
    private val context: Application = RuntimeEnvironment.getApplication()
    private val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private val player = AthanPlayer(context)
    private val created = mutableListOf<MediaPlayer>()

    @Before
    fun prepareMedia() {
        ShadowMediaPlayer.setMediaInfoProvider { ShadowMediaPlayer.MediaInfo(60_000, 0) }
        ShadowMediaPlayer.setCreateListener { media, _ -> created += media }
        audio.setStreamVolume(AudioManager.STREAM_ALARM, 2, 0)
    }

    @Test
    fun `starts immediately at full player and alarm volume`() {
        assertTrue(player.play())
        val media = shadowOf(created.last())
        assertEquals(1f, media.leftVolume, 0f)
        assertEquals(1f, media.rightVolume, 0f)
        assertEquals(AudioAttributes.USAGE_ALARM, media.audioAttributes.usage)
        assertEquals(audio.getStreamMaxVolume(AudioManager.STREAM_ALARM), audio.getStreamVolume(AudioManager.STREAM_ALARM))
        player.stop()
    }

    @Test
    fun `completion restores volume and releases focus without a manual stop`() {
        var completed: String? = null
        assertTrue(player.play(onFinished = { completed = it }))
        shadowOf(created.last()).invokeCompletionListener()
        assertEquals("Completed", completed)
        assertEquals(2, audio.getStreamVolume(AudioManager.STREAM_ALARM))
        assertFalse(player.isPlaying)
        assertNotNull(shadowOf(audio).lastAbandonedAudioFocusRequest)
        assertEquals(ShadowMediaPlayer.State.END, shadowOf(created.last()).state)
    }

    @Test
    fun `watchdog corrects a lowered alarm volume while playing`() {
        assertTrue(player.play())
        audio.setStreamVolume(AudioManager.STREAM_ALARM, 0, 0)
        assertTrue(player.ensureLoudAlarm())
        assertEquals(audio.getStreamMaxVolume(AudioManager.STREAM_ALARM), audio.getStreamVolume(AudioManager.STREAM_ALARM))
        player.stop()
        assertEquals(2, audio.getStreamVolume(AudioManager.STREAM_ALARM))
    }

    @Test
    fun `audio failure restores volume and releases every allocated player`() {
        ShadowMediaPlayer.setMediaInfoProvider { throw IllegalArgumentException("bad recording") }
        assertFalse(player.play())
        assertEquals(2, audio.getStreamVolume(AudioManager.STREAM_ALARM))
        assertTrue(created.isNotEmpty())
        assertTrue(created.all { shadowOf(it).state == ShadowMediaPlayer.State.END })
        assertNotNull(shadowOf(audio).lastAbandonedAudioFocusRequest)
    }

    @Test
    fun `decoder failure tries default alarm before reporting a final failure`() {
        var completed: String? = null
        assertTrue(player.play(onFinished = { completed = it }))
        val original = created.last()
        shadowOf(original).invokeErrorListener(1, 0)
        assertEquals(ShadowMediaPlayer.State.END, shadowOf(original).state)
        assertTrue(player.isPlaying)
        shadowOf(created.last()).invokeErrorListener(1, 0)
        assertTrue(completed?.startsWith("FAILED:") == true)
        assertFalse(player.isPlaying)
        assertEquals(2, audio.getStreamVolume(AudioManager.STREAM_ALARM))
    }
}
