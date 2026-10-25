package com.kpcl.plantalert

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale

/**
 * Foreground service holding the live Server-Sent-Events connection to the plant server. Every frame
 * goes through [AlertGate]; only critical alerts come out, and each one notifies + vibrates once.
 *
 * Each worker thread carries a generation number; stop/start bumps it, so an old worker that is
 * still sleeping or blocked on the network exits instead of running alongside the new one.
 */
class MonitorService : Service() {
    companion object {
        const val ACTION_STOP = "com.kpcl.plantalert.STOP"
        const val ACTION_RECONNECT = "com.kpcl.plantalert.RECONNECT"
        private const val LOST_AFTER_MS = 60_000L

        fun start(c: Context) {
            c.startForegroundService(Intent(c, MonitorService::class.java))
        }

        /** Re-read the server address / plant and reconnect now. */
        fun reconnect(c: Context) {
            c.startForegroundService(Intent(c, MonitorService::class.java).setAction(ACTION_RECONNECT))
        }

        fun stop(c: Context) {
            Prefs.setMonitoring(c, false)
            try {
                c.startService(Intent(c, MonitorService::class.java).setAction(ACTION_STOP))
            } catch (_: Exception) {
                // service not running and app in the background: nothing to stop
            }
            AlertStore.setConn("off")
        }
    }

    @Volatile private var generation = 0
    @Volatile private var conn: HttpURLConnection? = null
    private var worker: Thread? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var gate = AlertGate()
    private var gatePlant = ""
    private var lastMonitorText = ""
    private var lastMonitorMs = 0L

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            shutdown()
            return START_NOT_STICKY
        }
        // must be in the foreground within seconds of startForegroundService, whatever happens next
        Notifier.createChannels(this)
        val n = Notifier.monitorNotification(this, "Connecting…")
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(Notifier.MONITOR_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(Notifier.MONITOR_ID, n)
        }
        if (intent == null && !Prefs.monitoring(this)) {   // restarted by the system after the user stopped
            shutdown()
            return START_NOT_STICKY
        }
        Prefs.setMonitoring(this, true)
        if (wakeLock == null) {
            wakeLock = getSystemService(PowerManager::class.java)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "kpclplantalert:monitor")
                .apply { setReferenceCounted(false); acquire() }
        }
        if (intent?.action == ACTION_RECONNECT || worker?.isAlive != true) startWorker()
        return START_STICKY
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        // swiping the app away keeps the foreground service (stopWithTask=false)
        if (Prefs.monitoring(this)) Notifier.updateMonitor(this, "Still watching in the background")
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        generation++
        closeConnection()
        worker?.interrupt()
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
        super.onDestroy()
    }

    private fun shutdown() {
        generation++
        closeConnection()
        worker?.interrupt()
        worker = null
        Prefs.setMonitoring(this, false)
        AlertStore.setConn("off")
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun startWorker() {
        val gen = ++generation
        closeConnection()
        worker?.interrupt()
        AlertStore.setConn("connecting")
        worker = Thread({ loop(gen) }, "kpcl-monitor-$gen").also { it.start() }
    }

    private fun alive(gen: Int) = generation == gen

    private fun closeConnection() {
        try {
            conn?.disconnect()
        } catch (_: Exception) {
        }
        conn = null
    }

    private fun loop(gen: Int) {
        var backoffMs = 1000L
        var disconnectedSince = 0L
        while (alive(gen)) {
            try {
                streamOnce(gen) { backoffMs = 1000L; disconnectedSince = 0L }
            } catch (e: Exception) {
                if (!alive(gen)) break
                val now = System.currentTimeMillis()
                if (disconnectedSince == 0L) disconnectedSince = now
                val why = e.message ?: e.javaClass.simpleName
                if (now - disconnectedSince > LOST_AFTER_MS) {
                    // not critical, so no alert: say it in the app and in the silent status notice
                    AlertStore.setConn("lost", "No data for over a minute ($why). Critical alerts resume when the server is back.")
                    monitorText("Connection lost — retrying")
                } else {
                    AlertStore.setConn("reconnecting", "Reconnecting… ($why)")
                    monitorText("Reconnecting to server…")
                }
            }
            if (!alive(gen)) break
            try {
                Thread.sleep(backoffMs)
            } catch (_: InterruptedException) {
                if (!alive(gen)) break
            }
            backoffMs = (backoffMs * 2).coerceAtMost(15_000L)
        }
    }

    private fun streamOnce(gen: Int, onConnected: () -> Unit) {
        val base = Prefs.baseUrl(this)
        val plant = Prefs.plant(this)
        if (plant != gatePlant) {   // new plant: its breach history has nothing to do with the old one
            gate = AlertGate()
            gatePlant = plant
        }
        val c = URL("$base/live/stream?plant=$plant").openConnection() as HttpURLConnection
        conn = c
        c.connectTimeout = 8000
        c.readTimeout = 20_000   // the server sends a keep-alive comment several times a second
        c.setRequestProperty("Accept", "text/event-stream")
        try {
            if (c.responseCode !in 200..299) throw RuntimeException("server answered HTTP ${c.responseCode}")
            onConnected()
            c.inputStream.bufferedReader().use { r ->
                while (alive(gen)) {
                    val line = r.readLine() ?: throw RuntimeException("stream closed by server")
                    if (line.startsWith("data:")) handleFrame(line.substring(5).trim())
                }
            }
        } finally {
            c.disconnect()
        }
    }

    @Synchronized   // an old worker can still deliver one last frame while a new one starts
    private fun handleFrame(raw: String) {
        val f = try {
            Frame.parse(raw)
        } catch (_: Exception) {
            return   // one malformed frame should not drop the connection
        }
        AlertStore.setFrame(f, raw)
        monitorText("${plantLabel(f.plantId)} · %.0f kVA (%.0f%% of contract)".format(Locale.US, f.kva, f.contractPct * 100))
        for (a in gate.process(f)) {
            val title = when (a.kind) {
                "breach" -> "CONTRACT DEMAND BREACH · ${plantLabel(f.plantId)}"
                "anomaly_sustained" -> "MACHINE FAULT · ${a.assetId}"
                "demo" -> "DEMO CRITICAL ALERT · ${plantLabel(f.plantId)}"
                else -> "CRITICAL · ${a.assetId}"
            }
            Notifier.critical(this, a.key, title, a.message, f.ts)
        }
    }

    /** Silent status notice; rate-limited so a fast replay does not re-post it many times a second. */
    private fun monitorText(text: String) {
        val now = System.currentTimeMillis()
        if (text == lastMonitorText || (now - lastMonitorMs < 10_000 && !text.startsWith("Connection") && !text.startsWith("Reconnecting"))) return
        lastMonitorText = text
        lastMonitorMs = now
        Notifier.updateMonitor(this, text)
    }
}
