package com.kpcl.plantalert

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

data class AlertItem(val level: String, val title: String, val message: String, val simTs: String, val realMs: Long)

/** Recent alerts, persisted so the list survives the activity being closed. */
object AlertStore {
    private const val FILE = "kpcl_alert_store"
    private const val MAX = 60
    private val listeners = mutableListOf<() -> Unit>()

    @Volatile
    var status: String = "Not monitoring"
        private set

    @Synchronized
    fun add(c: Context, a: AlertItem) {
        val items = load(c)
        items.add(0, a)
        while (items.size > MAX) items.removeAt(items.size - 1)
        val json = JSONArray()
        items.forEach {
            json.put(
                JSONObject().put("l", it.level).put("t", it.title).put("m", it.message)
                    .put("s", it.simTs).put("r", it.realMs)
            )
        }
        c.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit().putString("items", json.toString()).apply()
        notifyListeners()
    }

    @Synchronized
    fun load(c: Context): MutableList<AlertItem> {
        val raw = c.getSharedPreferences(FILE, Context.MODE_PRIVATE).getString("items", "[]") ?: "[]"
        val out = mutableListOf<AlertItem>()
        val arr = JSONArray(raw)
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            out.add(AlertItem(o.getString("l"), o.getString("t"), o.getString("m"), o.getString("s"), o.getLong("r")))
        }
        return out
    }

    @Synchronized
    fun clear(c: Context) {
        c.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit().remove("items").apply()
        notifyListeners()
    }

    fun setStatus(s: String) {
        status = s
        notifyListeners()
    }

    @Synchronized
    fun addListener(l: () -> Unit) {
        listeners.add(l)
    }

    @Synchronized
    fun removeListener(l: () -> Unit) {
        listeners.remove(l)
    }

    @Synchronized
    private fun notifyListeners() {
        listeners.toList().forEach { it() }
    }
}
