package com.kpcl.plantalert

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Main screen: live status, start/stop, connection settings, tools, and the critical-alert history. */
class MainActivity : Activity() {
    private val ui = Ui(this)
    private val main = Handler(Looper.getMainLooper())

    private lateinit var pill: TextView
    private lateinit var alarmBanner: LinearLayout
    private lateinit var permCard: LinearLayout
    private lateinit var livePlant: TextView
    private lateinit var liveKva: TextView
    private lateinit var liveStatus: TextView
    private lateinit var liveBar: ProgressBar
    private lateinit var liveDetail: TextView
    private lateinit var liveTime: TextView
    private lateinit var toggleBtn: Button
    private lateinit var urlEdit: EditText
    private lateinit var connResult: TextView
    private lateinit var plantSpinner: Spinner
    private lateinit var bgStatus: TextView
    private lateinit var bgButton: Button
    private lateinit var alertList: LinearLayout

    private var plantIds = mutableListOf("ALL")
    private var plantNames = mutableListOf("All plants")
    private var shownHistory = -1
    private var refreshQueued = false

    // frames can arrive many times a second at high replay speed: coalesce UI refreshes
    private val listener: () -> Unit = {
        main.post {
            if (!refreshQueued) {
                refreshQueued = true
                main.postDelayed({ refreshQueued = false; refresh() }, 250)
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Notifier.createChannels(this)

        val root = ui.vertical()
        val header = ui.header("KPCL Plant Alert", "Critical-only energy pager")
        pill = ui.text("OFF", 11f, Color.WHITE, true).apply {
            setPadding(ui.dp(12), ui.dp(5), ui.dp(12), ui.dp(5))
            background = ui.shape(Ui.GREY, 20)
        }
        header.addView(pill)
        root.addView(header)

        val body = ui.vertical().apply { setPadding(ui.dp(14), ui.dp(14), ui.dp(14), ui.dp(28)) }
        root.addView(body)

        // ---- ringing banner ----
        alarmBanner = ui.vertical().apply {
            gravity = Gravity.CENTER
            background = ui.shape(Ui.RED, 14)
            setPadding(ui.dp(16), ui.dp(16), ui.dp(16), ui.dp(16))
            visibility = View.GONE
            addView(ui.text("CRITICAL ALARM", 18f, Color.WHITE, true))
            addView(ui.text("A critical plant condition needs attention", 13f, Color.WHITE, alpha = 0.9f), ui.lp(top = 2, bottom = 10))
            addView(Button(this@MainActivity).apply {
                text = "ACKNOWLEDGE"
                setTextColor(Ui.RED)
                textSize = 15f
                background = ui.shape(Color.WHITE, 12)
                stateListAnimator = null
                setOnClickListener { Notifier.acknowledgeAll(this@MainActivity) }
            }, ui.lp(h = ui.dp(50)))
        }
        body.addView(alarmBanner, ui.lp(bottom = 12))

        // ---- notifications blocked warning ----
        permCard = ui.card().apply {
            background = ui.shape(Color.parseColor("#FFF3E0"), 14, Ui.ORANGE)
            visibility = View.GONE
            addView(ui.text("Notifications are turned off", 15f, Ui.ORANGE, true))
            addView(ui.text("Critical alerts cannot reach you until notifications are allowed.", 12.5f, Ui.INK), ui.lp(top = 2, bottom = 8))
            addView(ui.outlineButton("Allow notifications", Ui.ORANGE).apply { setOnClickListener { askNotifications() } })
        }
        body.addView(permCard, ui.lp(bottom = 12))

        // ---- live card ----
        val live = ui.card()
        livePlant = ui.text("NOT MONITORING", 11f, Ui.GREY, true)
        liveKva = ui.text("— kVA", 36f, Ui.INK, true)
        liveStatus = ui.text("Press START to begin watching the plant", 13f, Ui.GREY, true)
        liveBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply { max = 100; progress = 0 }
        liveDetail = ui.text("", 12.5f, Ui.INK)
        liveTime = ui.text("", 11f, Ui.GREY)
        live.addView(livePlant)
        live.addView(liveKva)
        live.addView(liveStatus)
        live.addView(liveBar, ui.lp(top = 8, h = ui.dp(10)))
        live.addView(liveDetail, ui.lp(top = 6))
        live.addView(liveTime, ui.lp(top = 2))
        body.addView(live, ui.lp(bottom = 12))

        toggleBtn = ui.solidButton("START MONITORING", Ui.GREEN, 16f).apply { setOnClickListener { toggleMonitoring() } }
        body.addView(toggleBtn, ui.lp(bottom = 6, h = ui.dp(58)))
        body.addView(
            ui.text(
                "Only critical conditions notify and vibrate: a contract demand breach, a machine abnormal " +
                    "for 24 hours straight, or a critical alert sent from the dashboard.", 12f, Ui.GREY
            ).apply { gravity = Gravity.CENTER; setPadding(ui.dp(8), 0, ui.dp(8), 0) },
            ui.lp(bottom = 12)
        )

        // ---- connection ----
        val conn = ui.card()
        conn.addView(ui.text("Connection", 15f, Ui.INK, true))
        conn.addView(ui.fieldLabel("SERVER ADDRESS"))
        urlEdit = EditText(this).apply {
            setText(Prefs.baseUrl(this@MainActivity))
            hint = Prefs.DEFAULT_URL
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine()
            textSize = 15f
            contentDescription = "Server address"
        }
        conn.addView(urlEdit)
        conn.addView(ui.outlineButton("Save & connect").apply { setOnClickListener { saveAndConnect() } }, ui.lp(top = 6))
        connResult = ui.text("", 12f, Ui.GREY).apply { visibility = View.GONE }
        conn.addView(connResult, ui.lp(top = 6))

        conn.addView(ui.fieldLabel("PLANT TO WATCH"))
        plantSpinner = Spinner(this).apply { contentDescription = "Plant to watch" }
        conn.addView(plantSpinner)
        bindPlants()

        conn.addView(Switch(this).apply {
            text = "Alarm sound on critical alerts"
            contentDescription = "Alarm sound"
            isChecked = Prefs.alarmSound(this@MainActivity)
            setOnCheckedChangeListener { _, on -> Prefs.setAlarmSound(this@MainActivity, on) }
        }, ui.lp(top = 14))
        conn.addView(ui.text("Vibration and the notification always happen for critical alerts.", 11.5f, Ui.GREY))

        conn.addView(ui.fieldLabel("RUN IN BACKGROUND"))
        bgStatus = ui.text("", 12.5f, Ui.GREY)
        conn.addView(bgStatus)
        bgButton = ui.outlineButton("Allow background running").apply { setOnClickListener { requestBackgroundAllowed() } }
        conn.addView(bgButton, ui.lp(top = 6))
        body.addView(conn, ui.lp(bottom = 12))

        // ---- tools ----
        val tools = ui.card()
        tools.addView(ui.text("Tools", 15f, Ui.INK, true))
        tools.addView(ui.text("Check how a critical alert feels on this phone, or make the simulated plant hit its worst day.", 12f, Ui.GREY), ui.lp(top = 2, bottom = 10))
        val row = ui.horizontal()
        row.addView(ui.outlineButton("Test critical alert").apply { setOnClickListener { sendTestAlert() } }, ui.weight(right = 6))
        row.addView(ui.outlineButton("Jump to peak day").apply { setOnClickListener { jumpToPeakDay() } }, ui.weight(left = 6))
        tools.addView(row)
        tools.addView(ui.outlineButton("Developer console").apply {
            setOnClickListener { startActivity(Intent(this@MainActivity, DevConsoleActivity::class.java)) }
        }, ui.lp(top = 10))
        body.addView(tools, ui.lp(bottom = 12))

        // ---- history ----
        val ah = ui.horizontal()
        ah.addView(ui.text("Critical alerts", 16f, Ui.INK, true), LinearLayout.LayoutParams(0, -2, 1f))
        ah.addView(ui.text("Clear", 13f, Ui.BRAND, true).apply {
            setPadding(ui.dp(12), ui.dp(8), ui.dp(4), ui.dp(8))
            setOnClickListener { AlertStore.clear(this@MainActivity) }
        })
        body.addView(ah, ui.lp(top = 6, bottom = 4))
        alertList = ui.vertical()
        body.addView(alertList)

        body.addView(ui.text("Setup guide  ·  v" + versionName(), 12f, Ui.BRAND, true).apply {
            gravity = Gravity.CENTER
            setPadding(ui.dp(8), ui.dp(22), ui.dp(8), ui.dp(8))
            setOnClickListener {
                startActivity(Intent(this@MainActivity, WelcomeActivity::class.java).putExtra(WelcomeActivity.EXTRA_AGAIN, true))
            }
        }, ui.lp(top = 8))

        setContentView(ScrollView(this).apply {
            setBackgroundColor(Ui.PAGE)
            isFillViewport = true
            addView(root)
        })
    }

    override fun onStart() {
        super.onStart()
        AlertStore.addListener(listener)
        urlEdit.setText(Prefs.baseUrl(this))
        // monitoring was left on but the process was killed: bring the service back
        if (Prefs.monitoring(this) && AlertStore.conn == "off") MonitorService.start(this)
        loadPlants(Prefs.baseUrl(this), quiet = true)
        shownHistory = -1
        refresh()
    }

    override fun onStop() {
        AlertStore.removeListener(listener)
        super.onStop()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        refresh()
    }

    // ------------------------------------------------------------------ actions

    private fun typedUrl(): String? {
        val url = UrlCheck.normalize(urlEdit.text.toString())
        if (url == null) {
            toast("Enter a server address like ${Prefs.DEFAULT_URL}")
            urlEdit.error = "Not a valid address"
        }
        return url
    }

    private fun saveAndConnect() {
        val url = typedUrl() ?: return
        urlEdit.setText(url)
        Prefs.setBaseUrl(this, url)
        connResult.visibility = View.VISIBLE
        connResult.setTextColor(Ui.GREY)
        connResult.text = "Checking $url …"
        loadPlants(url, quiet = false)
        if (Prefs.monitoring(this)) MonitorService.reconnect(this)
    }

    private fun loadPlants(url: String, quiet: Boolean) {
        Thread {
            try {
                val plants = Api.plants(url)
                runOnUiThread {
                    plantIds = plants.map { it.id }.toMutableList()
                    plantNames = plants.map { it.name }.toMutableList()
                    bindPlants()
                    if (!quiet) {
                        connResult.setTextColor(Ui.GREEN)
                        connResult.text = "Connected · ${plants.size} plant options loaded"
                    }
                }
            } catch (e: Exception) {
                if (!quiet) runOnUiThread {
                    connResult.setTextColor(Ui.RED)
                    connResult.text = "Cannot reach $url (${e.message ?: e.javaClass.simpleName}). " +
                        "Check the server is running and the phone is on the same network."
                }
            }
        }.start()
    }

    private fun bindPlants() {
        val saved = Prefs.plant(this)
        if (saved !in plantIds) {   // list not loaded yet: still show what is selected
            plantIds.add(saved)
            plantNames.add(plantLabel(saved))
        }
        plantSpinner.onItemSelectedListener = null
        plantSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, plantNames)
        plantSpinner.setSelection(plantIds.indexOf(saved), false)
        plantSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                val chosen = plantIds.getOrNull(pos) ?: return
                if (chosen == Prefs.plant(this@MainActivity)) return
                Prefs.setPlant(this@MainActivity, chosen)
                if (Prefs.monitoring(this@MainActivity)) MonitorService.reconnect(this@MainActivity)
                toast("Watching ${plantNames[pos]}")
            }

            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
    }

    private fun toggleMonitoring() {
        if (Prefs.monitoring(this)) {
            MonitorService.stop(this)
            Notifier.acknowledgeAll(this)
        } else {
            val url = typedUrl() ?: return
            urlEdit.setText(url)
            Prefs.setBaseUrl(this, url)
            if (!Notifier.canNotify(this)) askNotifications()
            Prefs.setMonitoring(this, true)
            MonitorService.start(this)
            if (!isBackgroundAllowed()) requestBackgroundAllowed()
        }
        refresh()
    }

    private fun sendTestAlert() {
        if (!Notifier.canNotify(this)) askNotifications()
        Notifier.critical(
            this, "test:${System.currentTimeMillis()}", "TEST · Critical alert",
            "This is how a critical plant alert looks and feels. Tap ACKNOWLEDGE to silence it.", "test"
        )
    }

    private fun jumpToPeakDay() {
        val url = typedUrl() ?: return
        val plant = Prefs.plant(this)
        toast("Finding the highest-demand day…")
        Thread {
            try {
                val day = Api.worstDay(url, plant)
                Api.jump(url, day, 8.0)
                runOnUiThread {
                    toast(
                        "Replay jumped to $day (${plantLabel(plant)}'s highest-demand day) at 8x." +
                            if (Prefs.monitoring(this)) "" else " Start monitoring to get the alert."
                    )
                }
            } catch (e: Exception) {
                runOnUiThread { toast("Jump failed: ${e.message ?: e.javaClass.simpleName}") }
            }
        }.start()
    }

    private fun askNotifications() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            if (shouldShowRequestPermissionRationale(Manifest.permission.POST_NOTIFICATIONS) || !askedBefore()) {
                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
                return
            }
        }
        // permanently denied (or pre-13 with notifications switched off): only the settings page can fix it
        startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName))
    }

    private fun askedBefore(): Boolean {
        val sp = getSharedPreferences("kpcl_plant_alert", MODE_PRIVATE)
        val asked = sp.getBoolean("asked_notif", false)
        sp.edit().putBoolean("asked_notif", true).apply()
        return asked
    }

    private fun isBackgroundAllowed(): Boolean =
        getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(packageName)

    /** Without this, battery savers on many phones kill the monitor a few minutes after the app is closed. */
    private fun requestBackgroundAllowed() {
        try {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
        } catch (_: Exception) {
            try {
                startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            } catch (_: Exception) {
                toast("Open Settings › Apps › KPCL Plant Alert › Battery and choose Unrestricted")
            }
        }
    }

    private fun versionName(): String = try {
        packageManager.getPackageInfo(packageName, 0).versionName ?: "?"
    } catch (_: Exception) {
        "?"
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_LONG).show()

    // ------------------------------------------------------------------ rendering

    private fun refresh() {
        val on = Prefs.monitoring(this)
        val conn = if (on) AlertStore.conn else "off"

        permCard.visibility = if (Notifier.canNotify(this)) View.GONE else View.VISIBLE
        alarmBanner.visibility = if (AlarmPlayer.ringing) View.VISIBLE else View.GONE

        val bgOk = isBackgroundAllowed()
        bgStatus.text = if (bgOk) "Allowed — alerts keep coming when the app is closed." else "Restricted — the phone may stop alerts after the app is closed."
        bgStatus.setTextColor(if (bgOk) Ui.GREEN else Ui.ORANGE)
        bgButton.visibility = if (bgOk) View.GONE else View.VISIBLE

        val (pillText, pillColor) = when (conn) {
            "live" -> "LIVE" to Ui.GREEN
            "connecting" -> "CONNECTING" to Ui.ORANGE
            "reconnecting" -> "RECONNECTING" to Ui.ORANGE
            "lost" -> "NO DATA" to Ui.RED
            else -> "OFF" to Ui.GREY
        }
        pill.text = pillText
        pill.background = ui.shape(pillColor, 20)

        val f = AlertStore.frame
        if (on && f != null && conn == "live") {
            val color = when (f.status) {
                "critical" -> Ui.RED
                "watch" -> Ui.ORANGE
                else -> Ui.GREEN
            }
            livePlant.text = plantLabel(f.plantId).uppercase(Locale.ROOT)
            liveKva.text = "%.0f kVA".format(Locale.US, f.kva)
            liveKva.setTextColor(color)
            liveStatus.text = when (f.status) {
                "critical" -> "CRITICAL — contract demand breached (%.0f%%)".format(Locale.US, f.contractPct * 100)
                "watch" -> "Watch — %.0f%% of contract demand".format(Locale.US, f.contractPct * 100)
                else -> "Normal — %.0f%% of contract demand".format(Locale.US, f.contractPct * 100)
            }
            liveStatus.setTextColor(color)
            liveBar.progress = (f.contractPct * 100).toInt().coerceIn(0, 100)
            liveBar.progressTintList = ColorStateList.valueOf(color)
            liveDetail.text = "%.0f kW  ·  PF %.2f  ·  contract %.0f kVA  ·  today ₹%,.0f"
                .format(Locale.US, f.kw, f.pf, f.contractKva, f.costTodayRs)
            liveTime.text = "Replay time ${f.ts}  (simulated data)"
        } else {
            livePlant.text = if (on) plantLabel(Prefs.plant(this)).uppercase(Locale.ROOT) else "NOT MONITORING"
            liveKva.text = "— kVA"
            liveKva.setTextColor(Ui.INK)
            liveStatus.setTextColor(if (conn == "lost") Ui.RED else Ui.GREY)
            liveStatus.text = when {
                !on -> "Press START to begin watching the plant"
                conn == "reconnecting" || conn == "lost" -> AlertStore.detail
                else -> "Connecting to ${Prefs.baseUrl(this)} …"
            }
            liveBar.progress = 0
            liveDetail.text = ""
            liveTime.text = ""
        }

        toggleBtn.text = if (on) "STOP MONITORING" else "START MONITORING"
        toggleBtn.background = ui.shape(if (on) Ui.RED else Ui.GREEN, 12)

        if (shownHistory != AlertStore.historyVersion) {
            shownHistory = AlertStore.historyVersion
            renderHistory()
        }
    }

    private fun renderHistory() {
        alertList.removeAllViews()
        val items = AlertStore.load(this)
        if (items.isEmpty()) {
            alertList.addView(
                ui.text("No critical alerts. Use \"Test critical alert\", \"Jump to peak day\", or the dashboard's red button to see one.", 13f, Ui.GREY),
                ui.lp(top = 4)
            )
            return
        }
        val fmt = SimpleDateFormat("dd MMM HH:mm:ss", Locale.getDefault())
        for (a in items.take(40)) {
            val rowView = ui.horizontal().apply {
                gravity = Gravity.NO_GRAVITY
                background = ui.shape(Color.WHITE, 12)
                elevation = ui.dp(1).toFloat()
            }
            rowView.addView(View(this).apply { background = ui.shape(Ui.RED, 3) }, LinearLayout.LayoutParams(ui.dp(6), -1).apply {
                setMargins(ui.dp(8), ui.dp(8), 0, ui.dp(8))
            })
            val col = ui.vertical().apply { setPadding(ui.dp(12), ui.dp(10), ui.dp(12), ui.dp(10)) }
            col.addView(ui.text(a.title, 14f, Ui.RED, true))
            col.addView(ui.text(a.message, 13f, Ui.INK), ui.lp(top = 2))
            col.addView(ui.text("${fmt.format(Date(a.realMs))}  ·  replay ${a.simTs}", 11f, Ui.GREY), ui.lp(top = 4))
            rowView.addView(col, LinearLayout.LayoutParams(0, -2, 1f))
            alertList.addView(rowView, ui.lp(top = 8))
        }
    }
}
