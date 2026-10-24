package com.kpcl.plantalert

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale

/**
 * Foreground service that holds the live Server-Sent-Events connection to the plant server and turns
 * frames into notifications + beeps. It runs in the foreground so Android does not kill the connection
 * when the app is closed or the screen is off.
 */
class MonitorService : Service() {
    companion object {
        const val ACTION_STOP = "com.kpcl.plantalert.STOP"
        const val ACTION_RECONNECT = "com.kpcl.plantalert.RECONNECT"
        private const val LEAK_RS_PER_HR_THRESHOLD = 100.0

        fun start(c: Context) {
            c.startForegroundService(Intent(c, MonitorService::class.java))
        }

        fun stop(c: Context) {
            c.startService(Intent(c, MonitorService::class.java).setAction(ACTION_STOP))
        }

        fun reconnect(c: Context) {
            c.startService(Intent(c, MonitorService::class.java).setAction(ACTION_RECONNECT))
        }
    }

    @Volatile private var running = false
    @Volatile private var conn: HttpURLConnection? = null
    private var worker: Thread? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private val lastNotified = HashMap<String, Long>()
    private var lastStatusMs = 0L
    private var lastMonitorNotifMs = 0L

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                running = false
                Prefs.setMonitoring(this, false)
                AlertStore.setStatus("Not monitoring")
                closeConnection()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_RECONNECT -> {
                closeConnection()   // the worker loop reconnects using the current settings
                return START_STICKY
            }
        }

        Notifier.createChannels(this)
        val n = Notifier.monitorNotification(this, "Connecting…")
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(Notifier.MONITOR_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(Notifier.MONITOR_ID, n)
        }
        Prefs.setMonitoring(this, true)

        if (!running) {
            running = true
            val pm = getSystemService(PowerManager::class.java)
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "kpclplantalert:monitor").apply {
                setReferenceCounted(false)
                acquire()
            }
            worker = Thread({ loop() }, "kpcl-monitor").also { it.start() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        closeConnection()
        worker?.interrupt()
        wakeLock?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }

    private fun closeConnection() {
        try {
            conn?.disconnect()
        } catch (_: Exception) {
        }
    }

    private fun loop() {
        var backoffMs = 2000L
        var disconnectedSince = 0L
        var warnedLost = false
        while (running) {
            try {
                streamOnce { backoffMs = 2000L; disconnectedSince = 0L; warnedLost = false }
            } catch (e: Exception) {
                if (!running) break
                val now = System.currentTimeMillis()
                if (disconnectedSince == 0L) disconnectedSince = now
                AlertStore.setStatus("Reconnecting… (${e.javaClass.simpleName}: ${e.message ?: "no detail"})")
                Notifier.updateMonitor(this, "Reconnecting to server…")
                if (!warnedLost && now - disconnectedSince > 60_000) {
                    warnedLost = true
                    Notifier.alert(
                        this, "lost".hashCode(), "high", "Server unreachable",
                        "No data from the plant server for over a minute — alerts are paused until it is back.",
                        "—", Prefs.beep(this)
                    )
                }
            }
            if (!running) break
            try {
                Thread.sleep(backoffMs)
            } catch (_: InterruptedException) {
                break
            }
            backoffMs = (backoffMs * 2).coerceAtMost(20_000L)
        }
    }

    private fun streamOnce(onConnected: () -> Unit) {
        val base = Prefs.baseUrl(this)
        val plant = Prefs.plant(this)
        val url = "$base/live/stream" + if (plant != "ALL") "?plant=$plant" else ""
        val c = URL(url).openConnection() as HttpURLConnection
        conn = c
        c.connectTimeout = 8000
        c.readTimeout = 30_000   // the server sends keep-alive comments many times a second
        c.setRequestProperty("Accept", "text/event-stream")
        if (c.responseCode !in 200..299) throw RuntimeException("HTTP ${c.responseCode}")
        onConnected()
        AlertStore.setStatus("Connected · waiting for data")
        c.inputStream.bufferedReader().use { r ->
            while (running) {
                val line = r.readLine() ?: throw RuntimeException("stream closed")
                if (line.startsWith("data:")) handleFrame(JSONObject(line.substring(5).trim()), plant)
            }
        }
    }

    private fun label(plant: String) = if (plant == "ALL") "All plants" else plant.lowercase(Locale.ROOT).replaceFirstChar { it.uppercase() }

    private fun handleFrame(f: JSONObject, plant: String) {
        val ts = f.optString("ts")
        val p = f.getJSONObject("plant")
        val kva = p.optDouble("kVA", Double.NaN)
        val pct = p.optDouble("contract_pct", Double.NaN)
        val now = System.currentTimeMillis()

        if (now - lastStatusMs > 800) {
            lastStatusMs = now
            AlertStore.setStatus(
                "LIVE · ${label(plant)} · $ts\n%.0f kVA (%.0f%% of contract)".format(Locale.US, kva, pct * 100)
            )
        }
        if (now - lastMonitorNotifMs > 15_000) {
            lastMonitorNotifMs = now
            Notifier.updateMonitor(this, "${label(plant)} · %.0f kVA (%.0f%% of contract)".format(Locale.US, kva, pct * 100))
        }

        val minLevel = Prefs.minLevel(this)
        val alerts = f.optJSONArray("alerts")
        if (alerts != null) {
            for (i in 0 until alerts.length()) {
                val a = alerts.getJSONObject(i)
                val sev = a.optString("severity")
                val lvl = levelOf(sev)
                if (lvl < minLevel) continue
                val asset = a.optString("asset_id")
                val msg = a.optString("message")
                val kind = when {
                    msg.startsWith("Contract demand") -> "breach"
                    msg.startsWith("Demand at") -> "near-contract"
                    msg.startsWith("Power factor") -> "pf"
                    else -> "anomaly"
                }
                val title = when (kind) {
                    "breach" -> "CONTRACT DEMAND BREACH · ${label(plant)}"
                    "near-contract" -> "Demand near contract · ${label(plant)}"
                    "pf" -> "Low power factor · ${label(plant)}"
                    else -> "${sev.uppercase(Locale.ROOT)} anomaly · $asset"
                }
                // anomalies arrive in bursts across assets; one every 90 s is enough to act on
                val key = if (kind == "anomaly") "anomaly" else "$kind:$asset"
                notifyThrottled(key, if (kind == "breach") 30_000 else if (kind == "anomaly") 90_000 else 60_000, sev, title, msg, ts, lvl)
            }
        }

        // case a plant manager cares about that the server does not flag as an alert: money leaking away
        val comp = f.optJSONObject("compressor")
        val leakRs = comp?.optDouble("avoidable_leak_rs_per_hr", 0.0) ?: 0.0
        if (leakRs.isFinite() && leakRs > LEAK_RS_PER_HR_THRESHOLD && minLevel <= Prefs.LEVEL_HIGH) {
            notifyThrottled(
                "leak", 300_000, "high", "Air leak costing money · ${label(plant)}",
                "Compressed-air leak is wasting about ₹%.0f every hour above the normal background level.".format(Locale.US, leakRs),
                ts, 1
            )
        }
    }

    private fun levelOf(sev: String) = when (sev) {
        "critical" -> Prefs.LEVEL_CRITICAL
        "high" -> Prefs.LEVEL_HIGH
        else -> Prefs.LEVEL_ALL
    }

    private fun notifyThrottled(key: String, cooldownMs: Long, sev: String, title: String, msg: String, ts: String, lvl: Int) {
        val now = System.currentTimeMillis()
        val last = lastNotified[key] ?: 0L
        if (now - last < cooldownMs) return
        lastNotified[key] = now
        Notifier.alert(this, key.hashCode(), sev, title, msg, ts, Prefs.beep(this) && lvl >= Prefs.LEVEL_HIGH)
    }
}
