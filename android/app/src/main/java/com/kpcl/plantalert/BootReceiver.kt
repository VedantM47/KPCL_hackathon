package com.kpcl.plantalert

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Restarts monitoring after a reboot or app update if it was switched on. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val a = intent.action
        if ((a == Intent.ACTION_BOOT_COMPLETED || a == Intent.ACTION_MY_PACKAGE_REPLACED) && Prefs.monitoring(context)) {
            try {
                MonitorService.start(context)
            } catch (_: Exception) {
                // some OEM builds refuse background starts; opening the app restarts monitoring
            }
        }
    }
}
