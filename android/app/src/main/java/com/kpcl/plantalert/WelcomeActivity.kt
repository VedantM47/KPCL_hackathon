package com.kpcl.plantalert

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/**
 * First-launch screen: what the app does and where the plant server is. Shown once; the main screen's
 * "Setup guide" link reopens it ([EXTRA_AGAIN]).
 */
class WelcomeActivity : Activity() {
    companion object {
        const val EXTRA_AGAIN = "again"
    }

    private val ui = Ui(this)

    private fun feature(icon: Int, title: String, body: String): LinearLayout {
        val row = ui.horizontal().apply { setPadding(0, ui.dp(10), 0, ui.dp(10)) }
        row.addView(ImageView(this).apply {
            setImageResource(icon)
            setPadding(ui.dp(11), ui.dp(11), ui.dp(11), ui.dp(11))
            background = ui.shape(Color.parseColor("#E3EEF5"), 14)
        }, LinearLayout.LayoutParams(ui.dp(46), ui.dp(46)))
        val col = ui.vertical().apply { setPadding(ui.dp(14), 0, 0, 0) }
        col.addView(ui.text(title, 15f, Ui.INK, true))
        col.addView(ui.text(body, 12.5f, Ui.GREY).apply { setPadding(0, ui.dp(2), 0, 0) })
        row.addView(col, LinearLayout.LayoutParams(0, -2, 1f))
        return row
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val again = intent.getBooleanExtra(EXTRA_AGAIN, false)
        if (Prefs.onboarded(this) && !again) {
            startActivity(Intent(this, MainActivity::class.java))
            finish()
            return
        }
        Notifier.createChannels(this)
        if (!again && Build.VERSION.SDK_INT >= 33 && !Notifier.canNotify(this)) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }

        val root = ui.vertical()
        val hero = ui.vertical().apply {
            gravity = Gravity.CENTER_HORIZONTAL
            background = GradientDrawable(GradientDrawable.Orientation.TL_BR, intArrayOf(Color.parseColor("#16557F"), Color.parseColor("#0A2A44")))
            setPadding(ui.dp(24), ui.dp(44), ui.dp(24), ui.dp(36))
        }
        hero.addView(ImageView(this).apply {
            setImageResource(R.drawable.ic_logo)
            setPadding(ui.dp(14), ui.dp(14), ui.dp(14), ui.dp(14))
            background = ui.shape(Ui.BRAND_LIGHT, 28)
        }, LinearLayout.LayoutParams(ui.dp(96), ui.dp(96)))
        hero.addView(ui.text("KPCL Plant Alert", 26f, Color.WHITE, true).apply { gravity = Gravity.CENTER; setPadding(0, ui.dp(18), 0, 0) })
        hero.addView(ui.text("Your plant's critical-alert pager", 14f, Color.WHITE, alpha = 0.8f).apply { gravity = Gravity.CENTER; setPadding(0, ui.dp(4), 0, 0) })
        root.addView(hero)

        val body = ui.vertical().apply { setPadding(ui.dp(22), ui.dp(18), ui.dp(22), ui.dp(28)) }
        body.addView(feature(R.drawable.ic_bell, "Critical alerts only", "Notification and vibration only when the plant breaches its contract demand or a machine fault is confirmed. Nothing else buzzes."))
        body.addView(feature(R.drawable.ic_bars, "Live plant status", "Watch demand against the contract limit in real time."))
        body.addView(feature(R.drawable.ic_wifi, "Connects to your server", "Same Wi-Fi or laptop hotspot as the machine running the dashboard."))

        body.addView(ui.fieldLabel("SERVER ADDRESS").apply { setPadding(0, ui.dp(18), 0, ui.dp(2)) })
        val url = EditText(this).apply {
            setText(Prefs.baseUrl(this@WelcomeActivity))
            hint = Prefs.DEFAULT_URL
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine()
            textSize = 15f
            contentDescription = "Server address"
        }
        body.addView(url)
        body.addView(ui.text("Laptop hotspot is usually ${Prefs.DEFAULT_URL} · emulator: http://10.0.2.2:8000", 11.5f, Ui.GREY).apply { setPadding(0, ui.dp(4), 0, 0) })
        val check = ui.text("", 12f, Ui.GREY)
        body.addView(check, ui.lp(top = 6))

        body.addView(ui.outlineButton("Test connection").apply {
            setOnClickListener {
                val value = UrlCheck.normalize(url.text.toString())
                if (value == null) {
                    url.error = "Not a valid address"
                    return@setOnClickListener
                }
                check.setTextColor(Ui.GREY)
                check.text = "Checking $value …"
                Thread {
                    val msg = try {
                        "Connected · ${Api.plants(value).size} plant options" to Ui.GREEN
                    } catch (e: Exception) {
                        "Cannot reach $value (${e.message ?: e.javaClass.simpleName})" to Ui.RED
                    }
                    runOnUiThread { check.text = msg.first; check.setTextColor(msg.second) }
                }.start()
            }
        }, ui.lp(top = 14))

        val go = ui.solidButton(if (again) "SAVE" else "GET STARTED", Ui.TEAL, 16f).apply {
            setOnClickListener {
                val value = UrlCheck.normalize(url.text.toString())
                if (value == null) {
                    url.error = "Not a valid address"
                    Toast.makeText(this@WelcomeActivity, "Enter an address like ${Prefs.DEFAULT_URL}", Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }
                val changed = value != Prefs.baseUrl(this@WelcomeActivity)
                Prefs.setBaseUrl(this@WelcomeActivity, value)
                Prefs.setOnboarded(this@WelcomeActivity, true)
                if (changed && Prefs.monitoring(this@WelcomeActivity)) MonitorService.reconnect(this@WelcomeActivity)
                if (!again) startActivity(Intent(this@WelcomeActivity, MainActivity::class.java))
                finish()
            }
        }
        body.addView(go, ui.lp(top = 12, h = ui.dp(56)))
        root.addView(body)

        setContentView(ScrollView(this).apply {
            setBackgroundColor(Ui.PAGE)
            isFillViewport = true
            addView(root)
        })
    }
}
