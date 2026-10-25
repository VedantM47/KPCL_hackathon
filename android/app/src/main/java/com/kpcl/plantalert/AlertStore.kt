package com.kpcl.plantalert

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

data class AlertItem(val title: String, val message: String, val simTs: String, val realMs: Long)

/**
 * In-process state the UI observes: connection state, the latest frame, and the persisted history of
 * critical alerts (only critical alerts are ever stored — they are the only ones that notify).
 */
object AlertStore {
    private const val FILE = "kpcl_alert_store"
    private const val MAX = 60
    private val listeners = mutableListOf<() -> Unit>()

    /** off | connecting | live | reconnecting | lost */
    @Volatile var conn: String = "off"
        private set
    @Volatile var detail: String = ""
        private set
    @Volatile var frame: Frame? = null
        private set
    /** Raw JSON of the latest frame, for the developer console. */
    @Volatile var frameJson: String? = null
        private set
    /** Bumped whenever the stored alert list changes, so the UI only rebuilds the list when needed. */
    @Volatile var historyVersion = 0
        private set

    fun setConn(state: String, detail: String = "") {
        conn = state
        this.detail = detail
        if (state == "off") {
            frame = null
            frameJson = null
        }
        notifyListeners()
    }

    fun setFrame(f: Frame, raw: String) {
        frame = f
        frameJson = raw
        conn = "live"
        detail = ""
        notifyListeners()
    }

    @Synchronized
    fun add(c: Context, a: AlertItem) {
        val items = load(c)
        items.add(0, a)
        while (items.size > MAX) items.removeAt(items.size - 1)
        val json = JSONArray()
        items.forEach {
            json.put(JSONObject().put("t", it.title).put("m", it.message).put("s", it.simTs).put("r", it.realMs))
        }
        c.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit().putString("items_v2", json.toString()).apply()
        historyVersion++
        notifyListeners()
    }

    @Synchronized
    fun load(c: Context): MutableList<AlertItem> {
        val raw = c.getSharedPreferences(FILE, Context.MODE_PRIVATE).getString("items_v2", "[]") ?: "[]"
        return try {
            val arr = JSONArray(raw)
            (0 until arr.length()).map {
                val o = arr.getJSONObject(it)
                AlertItem(o.getString("t"), o.getString("m"), o.getString("s"), o.getLong("r"))
            }.toMutableList()
        } catch (_: Exception) {
            mutableListOf()
        }
    }

    @Synchronized
    fun clear(c: Context) {
        c.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit().remove("items_v2").remove("items").apply()
        historyVersion++
        notifyListeners()
    }

    /** Re-notify the UI without changing state (e.g. the alarm started or stopped). */
    fun touch() = notifyListeners()

    @Synchronized
    fun addListener(l: () -> Unit) {
        listeners.add(l)
    }

    @Synchronized
    fun removeListener(l: () -> Unit) {
        listeners.remove(l)
    }

    private fun notifyListeners() {
        val copy = synchronized(this) { listeners.toList() }
        copy.forEach { it() }
    }
}
