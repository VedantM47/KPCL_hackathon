package com.kpcl.plantalert

import android.Manifest
import android.app.Activity
import android.graphics.Color
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Single screen: server + plant + alert level, start/stop, a test button and the recent-alert list. */
class MainActivity : Activity() {
    private lateinit var statusView: TextView
    private lateinit var urlEdit: EditText
    private lateinit var plantSpinner: Spinner
    private lateinit var levelSpinner: Spinner
    private lateinit var toggleBtn: Button
    private lateinit var silenceBtn: Button
    private lateinit var alertList: LinearLayout

    private var plantIds = mutableListOf("ALL")
    private var plantNames = mutableListOf("All plants")
    private var ignoreSpinnerEvents = true

    private val listener: () -> Unit = { runOnUiThread { refresh() } }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun label(text: String, size: Float = 12f, bold: Boolean = false, color: Int = Color.DKGRAY) =
        TextView(this).apply {
            this.text = text
            textSize = size
            setTextColor(color)
            if (bold) setTypeface(typeface, Typeface.BOLD)
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Notifier.createChannels(this)
        if (Build.VERSION.SDK_INT >= 33) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(16), dp(16), dp(24))
        }

        root.addView(label("KPCL Plant Alert", 24f, true, Color.parseColor("#0F3D5E")))
        root.addView(label("Beeps and notifies you when the live plant monitor hits a critical condition.", 12f))

        statusView = label("Not monitoring", 15f, true).apply {
            setPadding(dp(12), dp(12), dp(12), dp(12))
            setBackgroundColor(Color.parseColor("#ECEFF1"))
        }
        root.addView(statusView, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(12) })
        silenceBtn = Button(this).apply {
            text = "ALARM RINGING - TAP TO ACKNOWLEDGE"
            setBackgroundColor(Color.parseColor("#C62828"))
            setTextColor(Color.WHITE)
            visibility = View.GONE
            setOnClickListener { AlarmPlayer.stop() }
        }
        root.addView(silenceBtn, LinearLayout.LayoutParams(-1, dp(56)).apply { topMargin = dp(8) })

        root.addView(label("Server address", 12f, true), LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(14) })
        urlEdit = EditText(this).apply {
            setText(Prefs.baseUrl(this@MainActivity))
            inputType = InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine()
        }
        root.addView(urlEdit)
        root.addView(Button(this).apply {
            text = "Save & load plants"
            setOnClickListener { saveUrlAndLoadPlants() }
        })

        root.addView(label("Plant to watch", 12f, true), LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(8) })
        plantSpinner = Spinner(this)
        root.addView(plantSpinner)
        bindPlants()

        root.addView(label("Alert when", 12f, true), LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(8) })
        levelSpinner = Spinner(this).apply {
            adapter = ArrayAdapter(
                this@MainActivity, android.R.layout.simple_spinner_dropdown_item,
                listOf("Everything", "High and critical", "Critical only")
            )
            setSelection(Prefs.minLevel(this@MainActivity))
            onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                    Prefs.setMinLevel(this@MainActivity, pos)
                }
                override fun onNothingSelected(p: AdapterView<*>?) {}
            }
        }
        root.addView(levelSpinner)

        root.addView(Switch(this).apply {
            text = "Loud beep for high/critical alerts"
            isChecked = Prefs.beep(this@MainActivity)
            setOnCheckedChangeListener { _, on -> Prefs.setBeep(this@MainActivity, on) }
        }, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(8) })

        toggleBtn = Button(this).apply {
            textSize = 16f
            setOnClickListener { toggleMonitoring() }
        }
        root.addView(toggleBtn, LinearLayout.LayoutParams(-1, dp(56)).apply { topMargin = dp(14) })

        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        row.addView(Button(this).apply {
            text = "Test alert"
            setOnClickListener { sendTestAlert() }
        }, LinearLayout.LayoutParams(0, -2, 1f))
        row.addView(Button(this).apply {
            text = "Demo: jump to peak day"
            setOnClickListener { jumpToPeakDay() }
        }, LinearLayout.LayoutParams(0, -2, 1f))
        root.addView(row)

        val header = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        header.addView(label("Recent alerts", 16f, true), LinearLayout.LayoutParams(0, -2, 1f))
        header.addView(Button(this).apply {
            text = "Clear"
            setOnClickListener { AlertStore.clear(this@MainActivity) }
        })
        root.addView(header, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(14) })
        alertList = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(alertList)

        setContentView(ScrollView(this).apply { addView(root) })
    }

    override fun onStart() {
        super.onStart()
        AlertStore.addListener(listener)
        // monitoring was left on but the process was killed/restarted: bring the service back
        if (Prefs.monitoring(this)) MonitorService.start(this)
        refresh()
    }

    override fun onStop() {
        AlertStore.removeListener(listener)
        super.onStop()
    }

    private fun bindPlants() {
        ignoreSpinnerEvents = true
        plantSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, plantNames)
        plantSpinner.setSelection(plantIds.indexOf(Prefs.plant(this)).coerceAtLeast(0))
        plantSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                if (ignoreSpinnerEvents) { ignoreSpinnerEvents = false; return }
                Prefs.setPlant(this@MainActivity, plantIds[pos])
                if (Prefs.monitoring(this@MainActivity)) MonitorService.reconnect(this@MainActivity)
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
    }

    private fun saveUrlAndLoadPlants() {
        val url = urlEdit.text.toString().trim().trimEnd('/')
        Prefs.setBaseUrl(this, url)
        Thread {
            try {
                val plants = Api.plants(url)
                runOnUiThread {
                    plantIds = plants.map { it.id }.toMutableList()
                    plantNames = plants.map { it.name }.toMutableList()
                    bindPlants()
                    toast("Connected — ${plants.size} plant options loaded")
                    if (Prefs.monitoring(this)) MonitorService.reconnect(this)
                }
            } catch (e: Exception) {
                runOnUiThread { toast("Cannot reach $url — ${e.message}") }
            }
        }.start()
    }

    private fun toggleMonitoring() {
        if (Prefs.monitoring(this)) {
            MonitorService.stop(this)
            Prefs.setMonitoring(this, false)
        } else {
            Prefs.setBaseUrl(this, urlEdit.text.toString())
            MonitorService.start(this)
            Prefs.setMonitoring(this, true)
        }
        refresh()
    }

    private fun sendTestAlert() {
        Notifier.createChannels(this)
        Notifier.alert(
            this, "test".hashCode(), "critical", "TEST · Contract demand breach",
            "This is how a critical plant alert looks and sounds. Tap ACKNOWLEDGE to silence it.", "test", true
        )
    }

    private fun jumpToPeakDay() {
        val url = urlEdit.text.toString().trim().trimEnd('/')
        val plant = Prefs.plant(this)
        Thread {
            try {
                val day = Api.worstDay(url, plant)
                Api.jump(url, day, 8.0)
                runOnUiThread { toast("Replay jumped to $day (highest-demand day), 8x speed") }
            } catch (e: Exception) {
                runOnUiThread { toast("Demo jump failed — ${e.message}") }
            }
        }.start()
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_LONG).show()

    private fun refresh() {
        silenceBtn.visibility = if (AlarmPlayer.ringing) View.VISIBLE else View.GONE
        val on = Prefs.monitoring(this)
        statusView.text = if (on) AlertStore.status else "Not monitoring"
        statusView.setTextColor(
            if (!on) Color.DKGRAY else if (AlertStore.status.startsWith("LIVE")) Color.parseColor("#2E7D32") else Color.parseColor("#EF6C00")
        )
        toggleBtn.text = if (on) "STOP MONITORING" else "START MONITORING"

        alertList.removeAllViews()
        val items = AlertStore.load(this)
        if (items.isEmpty()) {
            alertList.addView(label("No alerts yet. Start monitoring, then use “Demo: jump to peak day”.", 13f))
        }
        val fmt = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
        for (a in items.take(40)) {
            val color = when (a.level) {
                "critical" -> Color.parseColor("#C62828")
                "high" -> Color.parseColor("#EF6C00")
                else -> Color.DKGRAY
            }
            val box = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(10), dp(8), dp(10), dp(8))
                setBackgroundColor(Color.parseColor("#F5F5F5"))
            }
            box.addView(label(a.title, 14f, true, color))
            box.addView(label(a.message, 13f, false, Color.BLACK))
            box.addView(label("${fmt.format(Date(a.realMs))} · replay time ${a.simTs}", 11f))
            alertList.addView(box, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(6) })
        }
    }
}
