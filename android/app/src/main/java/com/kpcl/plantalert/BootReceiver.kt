package com.kpcl.plantalert

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Restarts monitoring after a reboot if it was switched on. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED && Prefs.monitoring(context)) {
            try {
                context.startForegroundService(Intent(context, MonitorService::class.java))
            } catch (_: Exception) {
                // some OEM builds refuse background starts; the user can reopen the app
            }
        }
    }
}
