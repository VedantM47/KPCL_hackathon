package com.kpcl.plantalert

import android.content.Context

/** Settings shared by the activities, the service and the boot receiver. */
object Prefs {
    private const val FILE = "kpcl_plant_alert"
    const val DEFAULT_URL = "http://192.168.137.1:8000"

    private fun sp(c: Context) = c.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun baseUrl(c: Context): String = sp(c).getString("url", DEFAULT_URL)!!
    fun setBaseUrl(c: Context, v: String) = sp(c).edit().putString("url", v).apply()

    fun plant(c: Context): String = sp(c).getString("plant", "ALL")!!
    fun setPlant(c: Context, v: String) = sp(c).edit().putString("plant", v).apply()

    /** Looping alarm sound on critical alerts. Notification + vibration happen either way. */
    fun alarmSound(c: Context): Boolean = sp(c).getBoolean("alarm_sound", true)
    fun setAlarmSound(c: Context, v: Boolean) = sp(c).edit().putBoolean("alarm_sound", v).apply()

    fun onboarded(c: Context): Boolean = sp(c).getBoolean("onboarded", false)
    fun setOnboarded(c: Context, v: Boolean) = sp(c).edit().putBoolean("onboarded", v).apply()

    fun monitoring(c: Context): Boolean = sp(c).getBoolean("monitoring", false)
    fun setMonitoring(c: Context, v: Boolean) = sp(c).edit().putBoolean("monitoring", v).apply()
}
