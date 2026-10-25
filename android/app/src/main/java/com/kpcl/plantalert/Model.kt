package com.kpcl.plantalert

import org.json.JSONObject
import java.net.URI

/** One alert inside a live frame. [key] identifies the condition across ticks (e.g. "breach:SASWAD"). */
data class LiveAlert(
    val severity: String,
    val kind: String,
    val key: String,
    val assetId: String,
    val message: String,
)

/** The parts of a /live/stream frame the app uses. Missing numbers are NaN. */
data class Frame(
    val idx: Int,
    val ts: String,
    val plantId: String,
    val status: String,
    val kw: Double,
    val kva: Double,
    val pf: Double,
    val contractKva: Double,
    val contractPct: Double,
    val costTodayRs: Double,
    val alerts: List<LiveAlert>,
    val demo: Boolean,
) {
    companion object {
        fun parse(raw: String): Frame {
            val o = JSONObject(raw)
            val p = o.getJSONObject("plant")
            val pct = p.optDouble("contract_pct", Double.NaN)
            val arr = o.optJSONArray("alerts")
            val alerts = (0 until (arr?.length() ?: 0)).map { i ->
                val a = arr!!.getJSONObject(i)
                val asset = a.optString("asset_id")
                val msg = a.optString("message")
                // older servers sent no kind/key; infer the one condition that repeats every tick
                val kind = a.optString("kind").ifEmpty { if (msg.startsWith("Contract demand")) "breach" else "event" }
                LiveAlert(a.optString("severity"), kind, a.optString("key").ifEmpty { "$kind:$asset" }, asset, msg)
            }
            return Frame(
                idx = o.optInt("idx", -1),
                ts = o.optString("ts"),
                plantId = o.optString("plant_id", "ALL"),
                status = o.optString("status").ifEmpty { statusOf(pct) },
                kw = p.optDouble("kW", Double.NaN),
                kva = p.optDouble("kVA", Double.NaN),
                pf = p.optDouble("pf", Double.NaN),
                contractKva = p.optDouble("contract_kva", Double.NaN),
                contractPct = pct,
                costTodayRs = o.optJSONObject("today")?.optDouble("cost_rs", Double.NaN) ?: Double.NaN,
                alerts = alerts,
                demo = o.optBoolean("demo", false),
            )
        }

        fun statusOf(pct: Double) = when {
            pct > 1.0 -> "critical"
            pct > 0.85 -> "watch"
            else -> "normal"
        }
    }
}

/**
 * Decides which alerts make the phone notify and vibrate. Only CRITICAL alerts ever do.
 *
 * A condition such as a contract breach repeats on every tick while it lasts, so it pages once per
 * episode: it can page again only after it has been absent for more than [clearTicks] ticks
 * (1 tick = 15 simulated minutes). One-off events (sustained anomaly, demo alert) page once per key.
 */
class AlertGate(private val clearTicks: Int = 4) {
    companion object {
        val CONDITION_KINDS = setOf("breach", "near_contract", "low_pf")
        private const val MAX_REMEMBERED = 500
    }

    private val lastSeen = HashMap<String, Int>()
    private val paged = LinkedHashSet<String>()
    private var lastIdx: Int? = null

    fun process(f: Frame): List<LiveAlert> {
        if (!f.demo && f.idx >= 0) {
            val prev = lastIdx
            // the replay jumped or wrapped around: whatever was going on before is over
            if (prev != null && (f.idx < prev || f.idx - prev > 8)) lastSeen.clear()
            lastIdx = f.idx
        }
        val out = mutableListOf<LiveAlert>()
        for (a in f.alerts) {
            if (a.severity != "critical") continue
            if (a.kind in CONDITION_KINDS) {
                val seen = lastSeen[a.key]
                if (seen == null || f.idx - seen > clearTicks) out.add(a)
                lastSeen[a.key] = f.idx
            } else if (paged.add(a.key)) {
                out.add(a)
                if (paged.size > MAX_REMEMBERED) paged.remove(paged.first())
            }
        }
        return out
    }
}

object UrlCheck {
    /** Cleans up a typed server address; null if it can't be a valid http(s) address. */
    fun normalize(input: String): String? {
        var s = input.trim()
        if (s.isEmpty()) return null
        if (!s.contains("://")) s = "http://$s"
        s = s.trimEnd('/')
        return try {
            val u = URI(s)
            if (u.scheme !in setOf("http", "https") || u.host.isNullOrEmpty()) null else s
        } catch (_: Exception) {
            null
        }
    }
}

/** "HADAPSAR" -> "Hadapsar", "ALL" -> "All plants". */
fun plantLabel(id: String): String =
    if (id == "ALL") "All plants" else id.lowercase().replaceFirstChar { it.uppercase() }
