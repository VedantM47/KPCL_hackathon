package com.kpcl.plantalert

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale

/**
 * Developer console: the data behind the app, with every term explained.
 *  - Live data: each field of the frame the monitor is receiving right now, its value, unit and meaning.
 *  - Dataset:   every table in the simulated database — what a row is, row count, each column explained,
 *               and pages of raw rows.
 *  - Glossary:  the energy / carbon terms used across the app and dashboard.
 * Explanations come from the server's /dev endpoints, so the app and the API never disagree.
 */
class DevConsoleActivity : Activity() {
    private companion object {
        const val PAGE_ROWS = 10
    }

    private val ui = Ui(this)
    private val main = Handler(Looper.getMainLooper())
    private lateinit var content: LinearLayout
    private val tabButtons = mutableListOf<Button>()
    private var tab = 0
    private var glossary: JSONObject? = null
    private var dataset: JSONObject? = null
    private val liveValues = HashMap<String, TextView>()

    private val tick = object : Runnable {
        override fun run() {
            if (tab == 0) updateLiveValues()
            main.postDelayed(this, 1000)
        }
    }

    private fun base() = Prefs.baseUrl(this)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = ui.vertical()
        val header = ui.header("Developer console", "Dataset and live data, explained")
        header.addView(ui.text("CLOSE", 12f, Color.WHITE, true).apply {
            setPadding(ui.dp(12), ui.dp(8), ui.dp(4), ui.dp(8))
            contentDescription = "Close developer console"
            setOnClickListener { finish() }
        })
        root.addView(header)

        val body = ui.vertical().apply { setPadding(ui.dp(14), ui.dp(12), ui.dp(14), ui.dp(28)) }
        body.addView(ui.text("All values are a benchmark-calibrated SIMULATION replayed as if live — not real KPCL meter data.", 12f, Ui.ORANGE, true).apply {
            background = ui.shape(Color.parseColor("#FFF3E0"), 10)
            setPadding(ui.dp(12), ui.dp(8), ui.dp(12), ui.dp(8))
        }, ui.lp(bottom = 10))

        val tabs = ui.horizontal()
        listOf("Live data", "Dataset", "Glossary").forEachIndexed { i, name ->
            val b = ui.outlineButton(name).apply { setOnClickListener { showTab(i) } }
            tabButtons.add(b)
            tabs.addView(b, ui.weight(left = if (i == 0) 0 else 4, right = if (i == 2) 0 else 4))
        }
        body.addView(tabs, ui.lp(bottom = 12))
        content = ui.vertical()
        body.addView(content)
        root.addView(body)

        setContentView(ScrollView(this).apply {
            setBackgroundColor(Ui.PAGE)
            isFillViewport = true
            addView(root)
        })
        showTab(0)
    }

    override fun onResume() {
        super.onResume()
        main.post(tick)
    }

    override fun onPause() {
        main.removeCallbacks(tick)
        super.onPause()
    }

    private fun showTab(i: Int) {
        tab = i
        tabButtons.forEachIndexed { j, b ->
            val on = j == i
            b.setTextColor(if (on) Color.WHITE else Ui.BRAND)
            b.background = ui.shape(if (on) Ui.BRAND else Color.WHITE, 12, Ui.BRAND)
        }
        content.removeAllViews()
        liveValues.clear()
        when (i) {
            0 -> withGlossary { renderLive(it) }
            1 -> withDataset { renderDataset(it) }
            else -> withGlossary { renderGlossary(it) }
        }
    }

    // ------------------------------------------------------------------ loading

    private fun loading(what: String) {
        content.removeAllViews()
        content.addView(ui.text("Loading $what from ${base()} …", 13f, Ui.GREY), ui.lp(top = 8))
    }

    private fun failed(what: String, e: Exception, retry: () -> Unit) {
        content.removeAllViews()
        val card = ui.card()
        card.addView(ui.text("Could not load $what", 15f, Ui.RED, true))
        card.addView(ui.text("${base()} — ${e.message ?: e.javaClass.simpleName}. Check the server address on the main screen and that the API is running.", 12.5f, Ui.INK), ui.lp(top = 4, bottom = 8))
        card.addView(ui.outlineButton("Retry").apply { setOnClickListener { retry() } })
        content.addView(card)
    }

    private fun <T> load(what: String, cached: T?, fetch: () -> T, store: (T) -> Unit, render: (T) -> Unit, forTab: Int) {
        if (cached != null) {
            render(cached)
            return
        }
        loading(what)
        Thread {
            try {
                val v = fetch()
                runOnUiThread {
                    store(v)
                    if (tab == forTab && !isFinishing) {
                        content.removeAllViews()
                        render(v)
                    }
                }
            } catch (e: Exception) {
                runOnUiThread { if (tab == forTab && !isFinishing) failed(what, e) { showTab(forTab) } }
            }
        }.start()
    }

    private fun withGlossary(render: (JSONObject) -> Unit) =
        load("explanations", glossary, { Api.glossary(base()) }, { glossary = it }, render, tab)

    private fun withDataset(render: (JSONObject) -> Unit) =
        load("the dataset", dataset, { Api.dataset(base()) }, { dataset = it }, render, tab)

    // ------------------------------------------------------------------ live data tab

    private fun renderLive(g: JSONObject) {
        content.addView(ui.text(
            "Each field the app receives from GET /live/stream on every tick (1 tick = 15 simulated minutes). " +
                "Values update every second while monitoring is on.", 12.5f, Ui.GREY
        ), ui.lp(bottom = 8))
        val status = ui.text("", 12f, Ui.GREY, true)
        liveValues["__status"] = status
        content.addView(status, ui.lp(bottom = 6))
        val fields = g.getJSONArray("live_fields")
        for (k in 0 until fields.length()) {
            val o = fields.getJSONObject(k)
            val card = ui.card().apply { setPadding(ui.dp(14), ui.dp(10), ui.dp(14), ui.dp(12)) }
            val top = ui.horizontal()
            top.addView(ui.mono(o.getString("field"), 13f, Ui.BRAND).apply { setTypeface(typeface, android.graphics.Typeface.BOLD) }, LinearLayout.LayoutParams(0, -2, 1f))
            val unit = o.optString("unit")
            if (unit.isNotEmpty()) top.addView(ui.text(unit, 11f, Ui.GREY, true))
            card.addView(top)
            val value = ui.mono("—", 14f, Ui.INK)
            liveValues[o.getString("field")] = value
            card.addView(value, ui.lp(top = 4))
            card.addView(ui.text(o.getString("meaning"), 12.5f, Ui.GREY), ui.lp(top = 4))
            content.addView(card, ui.lp(bottom = 8))
        }
        updateLiveValues()
    }

    private fun updateLiveValues() {
        if (liveValues.isEmpty()) return
        val raw = AlertStore.frameJson
        liveValues["__status"]?.text = when {
            raw != null -> "LIVE · ${plantLabel(Prefs.plant(this))}"
            Prefs.monitoring(this) -> "Waiting for the first frame…"
            else -> "Not monitoring — press START on the main screen to see live values. Meanings are shown below."
        }
        val f = raw?.let { runCatching { JSONObject(it) }.getOrNull() }
        for ((field, view) in liveValues) {
            if (field == "__status") continue
            view.text = if (f == null) "—" else valueAt(f, field)
        }
    }

    /** "plant.kVA" -> number, "assets[]" -> one line per machine, "alerts[].kind" -> each alert's kind. */
    private fun valueAt(f: JSONObject, path: String): String {
        if ("[]" in path) {
            val arrName = path.substringBefore("[]")
            val sub = path.substringAfter("[]").removePrefix(".")
            val arr = f.optJSONArray(arrName) ?: return "—"
            if (arr.length() == 0) return "(none on this tick)"
            return (0 until arr.length()).joinToString("\n") { i ->
                val o = arr.getJSONObject(i)
                when {
                    sub.isNotEmpty() -> show(o.opt(sub))
                    arrName == "assets" -> "%-16s %8s kW  %s".format(Locale.US, o.optString("asset_id"), show(o.opt("kW")), o.optString("state").takeIf { it != "null" } ?: "")
                    else -> "[${o.optString("severity")}] ${o.optString("message")}"
                }
            }
        }
        var cur: Any? = f
        for (part in path.split('.')) cur = (cur as? JSONObject)?.opt(part) ?: return "—"
        if (path == "plant.contract_pct") return (cur as? Number)?.let { "%.1f %%".format(Locale.US, it.toDouble() * 100) } ?: "—"
        return show(cur)
    }

    private fun show(v: Any?): String = when (v) {
        null, JSONObject.NULL -> "blank"
        is Double, is Float -> "%,.4f".format(Locale.US, (v as Number).toDouble()).trimEnd('0').trimEnd('.')
        is JSONArray -> "${v.length()} items"
        else -> v.toString()
    }

    // ------------------------------------------------------------------ dataset tab

    private fun renderDataset(d: JSONObject) {
        val tables = d.getJSONArray("tables")
        content.addView(ui.text(
            "${tables.length()} tables in the simulated database. Dimension tables describe things (plants, machines, " +
                "tariff); fact tables hold the 15-minute readings for 2025; rollups are pre-computed totals. Tap a table.",
            12.5f, Ui.GREY
        ), ui.lp(bottom = 8))
        for (k in 0 until tables.length()) content.addView(tableCard(tables.getJSONObject(k)), ui.lp(bottom = 8))
    }

    private fun tableCard(t: JSONObject): LinearLayout {
        val name = t.getString("table")
        val card = ui.card().apply { setPadding(ui.dp(14), ui.dp(12), ui.dp(14), ui.dp(12)) }
        val top = ui.horizontal()
        top.addView(ui.mono(name, 14f, Ui.BRAND).apply { setTypeface(typeface, android.graphics.Typeface.BOLD) }, LinearLayout.LayoutParams(0, -2, 1f))
        val chevron = ui.text("▸", 16f, Ui.BRAND, true)
        top.addView(chevron)
        card.addView(top)
        card.addView(ui.text("${t.getString("group")} · %,d rows · ${t.getJSONArray("columns").length()} columns".format(Locale.US, t.getLong("rows")), 11.5f, Ui.GREY, true), ui.lp(top = 2))
        card.addView(ui.text(t.getString("about"), 12.5f, Ui.INK), ui.lp(top = 4))

        val detail = ui.vertical().apply { visibility = View.GONE }
        card.addView(detail)
        card.isClickable = true
        card.contentDescription = "Table $name"
        card.setOnClickListener {
            val open = detail.visibility != View.VISIBLE
            detail.visibility = if (open) View.VISIBLE else View.GONE
            chevron.text = if (open) "▾" else "▸"
            if (open && detail.childCount == 0) buildTableDetail(t, detail)
        }
        return card
    }

    private fun buildTableDetail(t: JSONObject, detail: LinearLayout) {
        detail.addView(View(this).apply { setBackgroundColor(Ui.LINE) }, ui.lp(top = 10, bottom = 6, h = ui.dp(1)))
        detail.addView(ui.text("COLUMNS", 11f, Ui.GREY, true))
        val cols = t.getJSONArray("columns")
        for (k in 0 until cols.length()) {
            val c = cols.getJSONObject(k)
            val line = ui.vertical().apply { setPadding(0, ui.dp(6), 0, ui.dp(2)) }
            val unit = c.optString("unit")
            line.addView(ui.mono(c.getString("name") + "  " + c.optString("type").lowercase(Locale.ROOT) + if (unit.isNotEmpty()) "  [$unit]" else "", 12.5f, Ui.BRAND))
            line.addView(ui.text(c.getString("meaning"), 12.5f, Ui.INK))
            detail.addView(line)
        }
        detail.addView(View(this).apply { setBackgroundColor(Ui.LINE) }, ui.lp(top = 10, bottom = 6, h = ui.dp(1)))
        detail.addView(ui.text("SAMPLE ROWS", 11f, Ui.GREY, true))
        val grid = ui.vertical()
        val pager = ui.horizontal()
        val prev = ui.outlineButton("‹ Previous")
        val pos = ui.text("", 11.5f, Ui.GREY).apply { gravity = Gravity.CENTER }
        val next = ui.outlineButton("Next ›")
        pager.addView(prev, ui.weight(right = 4))
        pager.addView(pos, ui.weight())
        pager.addView(next, ui.weight(left = 4))
        detail.addView(HorizontalScrollView(this).apply { addView(grid) }, ui.lp(top = 6))
        detail.addView(pager, ui.lp(top = 8))

        val name = t.getString("table")
        val total = t.getLong("rows")
        var offset = 0
        fun loadPage() {
            prev.isEnabled = false
            next.isEnabled = false
            pos.text = "loading…"
            Thread {
                try {
                    val page = Api.rows(base(), name, offset, PAGE_ROWS)
                    runOnUiThread {
                        renderRows(grid, page)
                        val end = (offset + PAGE_ROWS).coerceAtMost(total.toInt())
                        pos.text = "rows %,d–%,d of %,d".format(Locale.US, offset + 1, end, total)
                        prev.isEnabled = offset > 0
                        next.isEnabled = end < total
                    }
                } catch (e: Exception) {
                    runOnUiThread {
                        pos.text = "failed: ${e.message ?: e.javaClass.simpleName}"
                        prev.isEnabled = offset > 0
                        next.isEnabled = true
                    }
                }
            }.start()
        }
        prev.setOnClickListener { offset = (offset - PAGE_ROWS).coerceAtLeast(0); loadPage() }
        next.setOnClickListener { offset += PAGE_ROWS; loadPage() }
        loadPage()
    }

    private fun renderRows(grid: LinearLayout, page: JSONObject) {
        grid.removeAllViews()
        val cols = page.getJSONArray("columns")
        val rows = page.getJSONArray("rows")
        val widths = IntArray(cols.length()) { c ->
            var w = cols.getString(c).length
            for (r in 0 until rows.length()) w = maxOf(w, cell(rows.getJSONArray(r).opt(c)).length)
            ui.dp((w.coerceIn(4, 28) * 7.5 + 12).toInt())
        }
        fun row(values: List<String>, headerRow: Boolean, shade: Boolean) {
            val line = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                setBackgroundColor(if (headerRow) Color.parseColor("#E3EEF5") else if (shade) Color.parseColor("#F7F9FB") else Color.WHITE)
            }
            values.forEachIndexed { c, v ->
                line.addView(ui.mono(v, 11.5f, if (headerRow) Ui.BRAND else Ui.INK).apply {
                    if (headerRow) setTypeface(typeface, android.graphics.Typeface.BOLD)
                    setPadding(ui.dp(6), ui.dp(5), ui.dp(6), ui.dp(5))
                    maxLines = 1
                }, LinearLayout.LayoutParams(widths[c], -2))
            }
            grid.addView(line)
        }
        row((0 until cols.length()).map { cols.getString(it) }, headerRow = true, shade = false)
        for (r in 0 until rows.length()) {
            val arr = rows.getJSONArray(r)
            row((0 until arr.length()).map { cell(arr.opt(it)) }, headerRow = false, shade = r % 2 == 1)
        }
    }

    private fun cell(v: Any?): String = when (v) {
        null, JSONObject.NULL -> "∅"
        else -> v.toString().let { if (it.length > 28) it.take(27) + "…" else it }
    }

    // ------------------------------------------------------------------ glossary tab

    private fun renderGlossary(g: JSONObject) {
        val terms = g.getJSONArray("terms")
        for (k in 0 until terms.length()) {
            val o = terms.getJSONObject(k)
            val card = ui.card().apply { setPadding(ui.dp(14), ui.dp(10), ui.dp(14), ui.dp(12)) }
            card.addView(ui.text(o.getString("term"), 14.5f, Ui.BRAND, true))
            card.addView(ui.text(o.getString("meaning"), 12.5f, Ui.INK), ui.lp(top = 3))
            content.addView(card, ui.lp(bottom = 8))
        }
    }
}
