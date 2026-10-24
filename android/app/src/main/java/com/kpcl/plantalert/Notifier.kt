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
import android.media.AudioManager
import android.media.Ringtone
import android.net.Uri
import android.media.RingtoneManager
import android.media.ToneGenerator
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator

/** Posts the heads-up notification and the audible beep for an alert. */
object Notifier {
    const val CHANNEL_MONITOR = "monitor"
    const val CHANNEL_ALERT = "alerts_v1"
    const val MONITOR_ID = 1
    private val main = Handler(Looper.getMainLooper())
    private var lastBeepMs = 0L

    fun createChannels(c: Context) {
        appContext = c.applicationContext
        val nm = c.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_MONITOR, "Monitoring status", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Shows that the app is watching the plant"
                setShowBadge(false)
            }
        )
        val alert = NotificationChannel(CHANNEL_ALERT, "Plant alerts", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Critical and high-priority plant conditions"
            enableVibration(true)
            setBypassDnd(true)   // only takes effect if the user grants Do Not Disturb access
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            vibrationPattern = longArrayOf(0, 400, 150, 400, 150, 600)
            val attrs = AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build()
            setSound(
                RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
                    ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION),
                attrs
            )
        }
        nm.createNotificationChannel(alert)
    }

    fun canNotify(c: Context): Boolean =
        Build.VERSION.SDK_INT < 33 ||
            c.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun openApp(c: Context): PendingIntent = PendingIntent.getActivity(
        c, 0,
        Intent(c, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_NEW_TASK),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )

    fun monitorNotification(c: Context, text: String): Notification =
        Notification.Builder(c, CHANNEL_MONITOR)
            .setSmallIcon(R.drawable.ic_stat_alert)
            .setContentTitle("KPCL Plant Alert is watching")
            .setContentText(text)
            .setContentIntent(openApp(c))
            .setOngoing(true)
            .build()

    fun updateMonitor(c: Context, text: String) {
        if (!canNotify(c)) return
        c.getSystemService(NotificationManager::class.java).notify(MONITOR_ID, monitorNotification(c, text))
    }

    /**
     * level: "critical" | "high" | other. Critical alerts behave like an on-call page: a looping alarm with
     * repeating vibration, a notification that stays until acknowledged, and a full-screen intent that wakes
     * the phone. [beep] lets the caller throttle sound separately from notifications.
     */
    fun alert(c: Context, id: Int, level: String, title: String, message: String, simTs: String, beep: Boolean) {
        AlertStore.add(c, AlertItem(level, title, message, simTs, System.currentTimeMillis()))
        val critical = level == "critical"
        val notifId = 1000 + (id and 0xFFFF)
        if (canNotify(c)) {
            val ack = PendingIntent.getBroadcast(
                c, notifId,
                Intent(c, AckReceiver::class.java).putExtra("id", notifId),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            val b = Notification.Builder(c, CHANNEL_ALERT)
                .setSmallIcon(R.drawable.ic_stat_alert)
                .setContentTitle(title)
                .setContentText(message)
                .setStyle(Notification.BigTextStyle().bigText("$message\nReplay time: $simTs"))
                .setCategory(Notification.CATEGORY_ALARM)
                .setColor(if (critical) 0xFFC62828.toInt() else 0xFFEF6C00.toInt())
                .setContentIntent(openApp(c))
                .setAutoCancel(!critical)
                .setWhen(System.currentTimeMillis())
                .addAction(Notification.Action.Builder(null, "ACKNOWLEDGE", ack).build())
            if (critical) b.setFullScreenIntent(openApp(c), true)
            c.getSystemService(NotificationManager::class.java).notify(notifId, b.build())
        }
        if (beep) {
            if (critical) AlarmPlayer.start(c) else beep(c, false)
        }
    }

    private var appContext: Context? = null

    fun cancelVibration() {
        appContext?.getSystemService(Vibrator::class.java)?.cancel()
    }

    /** Extra beep on the alarm stream so it is heard even when the notification sound is muted. */
    fun beep(c: Context, urgent: Boolean) {
        val now = System.currentTimeMillis()
        if (now - lastBeepMs < 4000) return
        lastBeepMs = now
        main.post {
            try {
                val tg = ToneGenerator(AudioManager.STREAM_ALARM, 100)
                val count = if (urgent) 3 else 1
                for (i in 0 until count) {
                    main.postDelayed({ tg.startTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, 350) }, i * 500L)
                }
                main.postDelayed({ tg.release() }, count * 500L + 600)
            } catch (_: Exception) {
                // no audio output available — the notification still shows
            }
            val v = c.getSystemService(Vibrator::class.java)
            if (v != null && v.hasVibrator()) {
                v.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 400, 150, 400, 150, 600), -1))
            }
        }
    }
}


/** Looping alarm + vibration for critical alerts; stops on acknowledge, on tapping the in-app button, or after two minutes. */
object AlarmPlayer {
    private val main = Handler(Looper.getMainLooper())
    private var ringtone: Ringtone? = null
    private val autoStop = Runnable { stop() }

    @Volatile
    var ringing = false
        private set

    fun start(c: Context) {
        main.post {
            if (ringing) {   // already ringing: just extend the timeout
                main.removeCallbacks(autoStop)
                main.postDelayed(autoStop, 120_000)
                return@post
            }
            try {
                val uri: Uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
                    ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
                val r = RingtoneManager.getRingtone(c.applicationContext, uri)
                r.audioAttributes = AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build()
                r.isLooping = true
                r.play()
                ringtone = r
            } catch (_: Exception) {
                Notifier.beep(c, true)   // no usable alarm sound: fall back to tones
            }
            val v = c.getSystemService(Vibrator::class.java)
            if (v != null && v.hasVibrator()) {
                v.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 700, 400, 700, 400, 1200, 800), 0))
            }
            ringing = true
            AlertStore.setStatus(AlertStore.status)   // refresh the UI so the acknowledge button appears
            main.postDelayed(autoStop, 120_000)
        }
    }

    fun stop() {
        main.post {
            main.removeCallbacks(autoStop)
            try {
                ringtone?.stop()
            } catch (_: Exception) {
            }
            ringtone = null
            ringing = false
            Notifier.cancelVibration()
            AlertStore.setStatus(AlertStore.status)
        }
    }
}
