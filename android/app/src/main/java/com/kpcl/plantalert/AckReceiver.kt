package com.kpcl.plantalert

import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** "ACKNOWLEDGE" button on an alert: silences the alarm and clears that notification. */
class AckReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        AlarmPlayer.stop()
        val id = intent.getIntExtra("id", -1)
        if (id >= 0) context.getSystemService(NotificationManager::class.java).cancel(id)
    }
}
