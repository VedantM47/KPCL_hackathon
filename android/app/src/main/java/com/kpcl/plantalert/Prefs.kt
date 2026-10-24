package com.kpcl.plantalert

import android.content.Context

/** Settings shared by the activity, the service and the boot receiver. */
object Prefs {
    private const val FILE = "kpcl_plant_alert"

    // 0 = everything, 1 = high and above, 2 = critical only
    const val LEVEL_ALL = 0
    const val LEVEL_HIGH = 1
    const val LEVEL_CRITICAL = 2

    private fun sp(c: Context) = c.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun baseUrl(c: Context): String = sp(c).getString("url", "http://10.0.2.2:8000")!!.trim().trimEnd('/')
    fun setBaseUrl(c: Context, v: String) = sp(c).edit().putString("url", v.trim().trimEnd('/')).apply()

    fun plant(c: Context): String = sp(c).getString("plant", "ALL")!!
    fun setPlant(c: Context, v: String) = sp(c).edit().putString("plant", v).apply()

    fun minLevel(c: Context): Int = sp(c).getInt("level", LEVEL_HIGH)
    fun setMinLevel(c: Context, v: Int) = sp(c).edit().putInt("level", v).apply()

    fun beep(c: Context): Boolean = sp(c).getBoolean("beep", true)
    fun setBeep(c: Context, v: Boolean) = sp(c).edit().putBoolean("beep", v).apply()

    fun monitoring(c: Context): Boolean = sp(c).getBoolean("monitoring", false)
    fun setMonitoring(c: Context, v: Boolean) = sp(c).edit().putBoolean("monitoring", v).apply()
}
