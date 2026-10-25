package com.kpcl.plantalert

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.Ringtone
import android.media.RingtoneManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.VibrationAttributes
import android.os.VibrationEffect
import android.os.Vibrator

/**
 * Notifications. There are exactly two kinds:
 *  - the silent, ongoing "monitoring" notice Android requires for a foreground service;
 *  - CRITICAL alerts: heads-up notification + vibration (+ looping alarm sound if enabled).
 * Nothing else ever notifies or vibrates.
 */
object Notifier {
    const val CHANNEL_STATUS = "status_v2"
    const val CHANNEL_CRITICAL = "critical_v2"
    const val MONITOR_ID = 1
    private val OLD_CHANNELS = listOf("monitor", "alerts_v1")
    private val active = LinkedHashSet<Int>()

    fun createChannels(c: Context) {
        val nm = c.getSystemService(NotificationManager::class.java)
        OLD_CHANNELS.forEach { nm.deleteNotificationChannel(it) }
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_STATUS, "Monitoring status", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Silent notice that the app is watching the plant"
                setShowBadge(false)
                setSound(null, null)
                enableVibration(false)
            }
        )
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_CRITICAL, "Critical plant alerts", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Contract demand breach and confirmed machine faults only"
                lockscreenVisibility = Notification.VISIBILITY_PUBLIC
                setBypassDnd(true)   // only takes effect if the user grants it in system settings
                // sound and vibration are driven by AlarmPlayer so ACKNOWLEDGE can stop them
                setSound(null, null)
                enableVibration(false)
            }
        )
    }

    fun canNotify(c: Context): Boolean =
        Build.VERSION.SDK_INT < 33 ||
            c.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun openApp(c: Context, req: Int = 0): PendingIntent = PendingIntent.getActivity(
        c, req,
        Intent(c, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_NEW_TASK),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )

    fun monitorNotification(c: Context, text: String): Notification =
        Notification.Builder(c, CHANNEL_STATUS)
            .setSmallIcon(R.drawable.ic_stat_alert)
            .setContentTitle("KPCL Plant Alert is watching")
            .setContentText(text)
            .setContentIntent(openApp(c))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()

    fun updateMonitor(c: Context, text: String) {
        if (!canNotify(c)) return
        c.getSystemService(NotificationManager::class.java).notify(MONITOR_ID, monitorNotification(c, text))
    }

    /** Raise a critical alert: history entry, heads-up notification, vibration and (optionally) alarm sound. */
    fun critical(c: Context, key: String, title: String, message: String, simTs: String) {
        val notifId = 1000 + (key.hashCode() and 0xFFFF)
        AlertStore.add(c, AlertItem(title, message, simTs, System.currentTimeMillis()))
        if (canNotify(c)) {
            val ack = PendingIntent.getBroadcast(
                c, notifId,
                Intent(c, AckReceiver::class.java).putExtra(AckReceiver.EXTRA_ID, notifId),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            val n = Notification.Builder(c, CHANNEL_CRITICAL)
                .setSmallIcon(R.drawable.ic_stat_alert)
                .setContentTitle(title)
                .setContentText(message)
                .setStyle(Notification.BigTextStyle().bigText("$message\nReplay time: $simTs"))
                .setCategory(Notification.CATEGORY_ALARM)
                .setColor(0xFFC62828.toInt())
                .setContentIntent(openApp(c, notifId))
                .setFullScreenIntent(openApp(c, notifId + 1), true)
                .setAutoCancel(false)
                .setWhen(System.currentTimeMillis())
                .setShowWhen(true)
                .addAction(Notification.Action.Builder(null, "ACKNOWLEDGE", ack).build())
                .build()
            c.getSystemService(NotificationManager::class.java).notify(notifId, n)
            synchronized(active) { active.add(notifId) }
        }
        AlarmPlayer.start(c, Prefs.alarmSound(c))
    }

    /** ACKNOWLEDGE from the notification: silence the alarm and clear that one notification. */
    fun acknowledge(c: Context, notifId: Int) {
        AlarmPlayer.stop(c)
        c.getSystemService(NotificationManager::class.java).cancel(notifId)
        synchronized(active) { active.remove(notifId) }
    }

    /** ACKNOWLEDGE in the app: silence the alarm and clear every critical notification. */
    fun acknowledgeAll(c: Context) {
        AlarmPlayer.stop(c)
        val nm = c.getSystemService(NotificationManager::class.java)
        val ids = synchronized(active) { active.toList().also { active.clear() } }
        ids.forEach { nm.cancel(it) }
    }
}

/**
 * Critical-alert alarm: vibration pulses and, if enabled, a looping alarm-stream sound, until
 * acknowledged or [RING_MS] elapses. Each pulse checks [ringing], so it ends right away on acknowledge.
 */
object AlarmPlayer {
    private const val RING_MS = 120_000L
    private val main = Handler(Looper.getMainLooper())
    private var ringtone: Ringtone? = null
    private var vibrator: Vibrator? = null
    private var appContext: Context? = null
    private val autoStop = Runnable { appContext?.let { stop(it) } }

    @Volatile
    var ringing = false
        private set

    private val alarmAudio = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_ALARM)
        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
        .build()

    private val pulse = object : Runnable {
        override fun run() {
            if (!ringing) return
            vibrate(VibrationEffect.createWaveform(longArrayOf(0, 500, 200, 500), -1))
            main.postDelayed(this, 1600)
        }
    }

    private fun vibrate(effect: VibrationEffect) {
        val v = vibrator ?: return
        try {
            // alarm usage: still vibrates in silent mode and while the app is in the background
            if (Build.VERSION.SDK_INT >= 33) {
                v.vibrate(effect, VibrationAttributes.createForUsage(VibrationAttributes.USAGE_ALARM))
            } else {
                @Suppress("DEPRECATION")
                v.vibrate(effect, alarmAudio)
            }
        } catch (_: Exception) {
        }
    }

    fun start(c: Context, sound: Boolean) {
        val app = c.applicationContext
        main.post {
            appContext = app
            main.removeCallbacks(autoStop)
            main.postDelayed(autoStop, RING_MS)
            if (ringing) return@post   // a second critical alert while ringing just extends it
            ringing = true
            vibrator = app.getSystemService(Vibrator::class.java)?.takeIf { it.hasVibrator() }
            main.post(pulse)
            if (sound) {
                try {
                    val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
                        ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
                    ringtone = RingtoneManager.getRingtone(app, uri)?.apply {
                        audioAttributes = alarmAudio
                        if (Build.VERSION.SDK_INT >= 28) isLooping = true
                        play()
                    }
                } catch (_: Exception) {
                    ringtone = null   // no usable alarm sound: vibration + notification still happen
                }
            }
            AlertStore.touch()
        }
    }

    fun stop(c: Context) {
        ringing = false   // immediate: the pulse loop checks it before every vibration
        val app = c.applicationContext
        main.post {
            main.removeCallbacks(pulse)
            main.removeCallbacks(autoStop)
            try {
                ringtone?.stop()
            } catch (_: Exception) {
            }
            ringtone = null
            try {
                (vibrator ?: app.getSystemService(Vibrator::class.java))?.cancel()
            } catch (_: Exception) {
            }
            AlertStore.touch()
        }
    }
}
