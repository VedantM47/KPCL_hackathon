package com.kpcl.plantalert

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** Minimal blocking HTTP helpers; always call from a background thread. */
object Api {
    private fun open(url: String, method: String = "GET", timeoutMs: Int = 8000): HttpURLConnection {
        val c = URL(url).openConnection() as HttpURLConnection
        c.requestMethod = method
        c.connectTimeout = timeoutMs
        c.readTimeout = timeoutMs
        return c
    }

    private fun read(c: HttpURLConnection): String {
        try {
            if (c.responseCode !in 200..299) throw RuntimeException("server answered HTTP ${c.responseCode}")
            return c.inputStream.bufferedReader().readText()
        } finally {
            c.disconnect()
        }
    }

    fun getText(url: String): String = read(open(url))

    fun postJson(url: String, body: JSONObject): String {
        val c = open(url, "POST")
        c.doOutput = true
        c.setRequestProperty("Content-Type", "application/json")
        c.outputStream.use { it.write(body.toString().toByteArray()) }
        return read(c)
    }

    data class Plant(val id: String, val name: String)

    fun plants(base: String): List<Plant> {
        val arr = JSONArray(getText("$base/plants"))
        return (0 until arr.length()).map {
            val o = arr.getJSONObject(it)
            Plant(o.getString("plant_id"), o.getString("name"))
        }
    }

    /** Date of the plant's highest-demand day; the demo button jumps the replay there. */
    fun worstDay(base: String, plant: String): String {
        val arr = JSONArray(getText("$base/schedule/days?top_n=1&plant=$plant"))
        return arr.getJSONObject(0).getString("date")
    }

    fun jump(base: String, date: String, speed: Double): JSONObject = JSONObject(
        postJson("$base/live/control", JSONObject().put("jump_to", "$date 05:30").put("speed", speed).put("paused", false))
    )

    // ---- developer console ----
    fun dataset(base: String): JSONObject = JSONObject(getText("$base/dev/dataset"))

    fun rows(base: String, table: String, offset: Int, limit: Int): JSONObject =
        JSONObject(getText("$base/dev/dataset/${URLEncoder.encode(table, "UTF-8")}?offset=$offset&limit=$limit"))

    fun glossary(base: String): JSONObject = JSONObject(getText("$base/dev/glossary"))
}
