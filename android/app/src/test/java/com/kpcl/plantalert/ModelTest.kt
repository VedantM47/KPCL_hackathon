package com.kpcl.plantalert

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ModelTest {
    private fun alert(sev: String, kind: String, key: String, asset: String = "PLANT") =
        JSONObject().put("severity", sev).put("kind", kind).put("key", key).put("asset_id", asset).put("message", "$kind msg")

    private fun frame(idx: Int, vararg alerts: JSONObject, pct: Double = 0.5, demo: Boolean = false): Frame {
        val o = JSONObject()
            .put("idx", idx).put("ts", "2025-03-01 10:00:00").put("plant_id", "SASWAD")
            .put("plant", JSONObject().put("kW", 40.0).put("kVA", 42.0).put("pf", 0.95).put("contract_kva", 80.0).put("contract_pct", pct))
            .put("today", JSONObject().put("cost_rs", 1234.5))
            .put("alerts", JSONArray(alerts.toList()))
        if (demo) o.put("demo", true)
        return Frame.parse(o.toString())
    }

    private fun breach() = alert("critical", "breach", "breach:SASWAD")

    // ---------------------------------------------------------------- parsing

    @Test fun parsesAFullFrame() {
        val f = frame(7, breach(), pct = 1.08)
        assertEquals(7, f.idx)
        assertEquals("SASWAD", f.plantId)
        assertEquals(42.0, f.kva, 0.0)
        assertEquals(80.0, f.contractKva, 0.0)
        assertEquals(1234.5, f.costTodayRs, 0.0)
        assertEquals("critical", f.status)   // derived from contract_pct when the server sends no status
        assertEquals(listOf("breach:SASWAD"), f.alerts.map { it.key })
    }

    @Test fun nullNumbersBecomeNaNNotCrash() {
        val f = Frame.parse("""{"idx":1,"ts":"t","plant":{"kW":null,"kVA":null,"pf":null,"contract_kva":80,"contract_pct":null},"alerts":[]}""")
        assertTrue(f.kva.isNaN())
        assertTrue(f.contractPct.isNaN())
        assertEquals("normal", f.status)
        assertTrue(f.alerts.isEmpty())
    }

    @Test fun serverStatusWins() {
        val raw = """{"idx":1,"ts":"t","status":"watch","plant":{"contract_pct":0.2},"alerts":[]}"""
        assertEquals("watch", Frame.parse(raw).status)
    }

    @Test fun oldServerAlertsWithoutKindStillClassify() {
        val raw = """{"idx":1,"ts":"t","plant":{"contract_pct":1.1},"alerts":[
            {"severity":"critical","asset_id":"PLANT","message":"Contract demand breached: 90 kVA vs 80"},
            {"severity":"critical","asset_id":"CNC-GEAR-01","message":"CNC-GEAR-01 anomaly starts"}]}"""
        val a = Frame.parse(raw).alerts
        assertEquals("breach", a[0].kind)
        assertEquals("breach:PLANT", a[0].key)
        assertEquals("event", a[1].kind)
    }

    @Test fun statusThresholds() {
        assertEquals("normal", Frame.statusOf(0.85))
        assertEquals("watch", Frame.statusOf(0.86))
        assertEquals("watch", Frame.statusOf(1.0))
        assertEquals("critical", Frame.statusOf(1.01))
    }

    // ---------------------------------------------------------------- the critical-only rule

    @Test fun nonCriticalAlertsNeverPage() {
        val g = AlertGate()
        val out = g.process(frame(1,
            alert("high", "near_contract", "near:SASWAD"),
            alert("medium", "low_pf", "pf:SASWAD"),
            alert("high", "anomaly", "anomaly:CNC:1", "CNC-GEAR-01"),
            alert("low", "anomaly", "anomaly:CNC:2", "CNC-GEAR-01")))
        assertTrue(out.isEmpty())
    }

    @Test fun breachPagesOncePerEpisodeNotEveryTick() {
        val g = AlertGate(clearTicks = 4)
        assertEquals(1, g.process(frame(10, breach())).size)
        for (i in 11..40) assertTrue("tick $i re-paged", g.process(frame(i, breach())).isEmpty())
    }

    @Test fun breachThatFlickersDoesNotRepage() {
        val g = AlertGate(clearTicks = 4)
        assertEquals(1, g.process(frame(10, breach())).size)
        g.process(frame(11))
        g.process(frame(12))
        assertTrue(g.process(frame(13, breach())).isEmpty())   // gone 2 ticks: same episode
    }

    @Test fun newEpisodeAfterItClearsPagesAgain() {
        val g = AlertGate(clearTicks = 4)
        g.process(frame(10, breach()))
        for (i in 11..15) g.process(frame(i))
        assertEquals(1, g.process(frame(16, breach())).size)   // clear for 5 ticks: a new breach
    }

    @Test fun replayJumpStartsFresh() {
        val g = AlertGate()
        g.process(frame(10, breach()))
        assertEquals(1, g.process(frame(5000, breach())).size)   // jumped forward
        assertEquals(1, g.process(frame(3, breach())).size)      // wrapped around
    }

    @Test fun eventsPageOncePerKey() {
        val g = AlertGate()
        val fault = alert("critical", "anomaly_sustained", "anomaly24h:CHILLER:100", "CHILLER-SCR-01")
        assertEquals(1, g.process(frame(195, fault)).size)
        assertTrue(g.process(frame(195, fault)).isEmpty())   // same frame again after a reconnect
        val other = alert("critical", "anomaly_sustained", "anomaly24h:CHILLER:900", "CHILLER-SCR-01")
        assertEquals(1, g.process(frame(995, other)).size)
    }

    @Test fun eachDemoAlertPages() {
        val g = AlertGate()
        assertEquals(1, g.process(frame(50, alert("critical", "demo", "demo:1"), demo = true)).size)
        assertEquals(1, g.process(frame(50, alert("critical", "demo", "demo:2"), demo = true)).size)
        assertTrue(g.process(frame(50, alert("critical", "demo", "demo:2"), demo = true)).isEmpty())
    }

    @Test fun demoFrameDoesNotBreakBreachEpisode() {
        val g = AlertGate()
        g.process(frame(10, breach()))
        g.process(frame(10, alert("critical", "demo", "demo:9"), demo = true))
        assertTrue(g.process(frame(11, breach())).isEmpty())
    }

    @Test fun breachAndFaultTogetherBothPage() {
        val g = AlertGate()
        val out = g.process(frame(10, breach(), alert("critical", "anomaly_sustained", "anomaly24h:X:1", "X")))
        assertEquals(listOf("breach", "anomaly_sustained"), out.map { it.kind })
    }

    // ---------------------------------------------------------------- server address

    @Test fun urlNormalisation() {
        assertEquals("http://192.168.137.1:8000", UrlCheck.normalize(" http://192.168.137.1:8000/ "))
        assertEquals("http://10.0.2.2:8000", UrlCheck.normalize("10.0.2.2:8000"))
        assertEquals("https://abc.trycloudflare.com", UrlCheck.normalize("https://abc.trycloudflare.com"))
        assertNull(UrlCheck.normalize(""))
        assertNull(UrlCheck.normalize("   "))
        assertNull(UrlCheck.normalize("ftp://host"))
        assertNull(UrlCheck.normalize("http://"))
        assertNull(UrlCheck.normalize("http://bad host"))
    }

    @Test fun plantLabels() {
        assertEquals("All plants", plantLabel("ALL"))
        assertEquals("Hadapsar", plantLabel("HADAPSAR"))
    }
}
