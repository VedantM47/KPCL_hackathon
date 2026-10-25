package com.kpcl.plantalert

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** "ACKNOWLEDGE" button on a critical alert: silences the alarm and clears that notification. */
class AckReceiver : BroadcastReceiver() {
    companion object {
        const val EXTRA_ID = "id"
    }

    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getIntExtra(EXTRA_ID, -1)
        if (id >= 0) Notifier.acknowledge(context, id) else Notifier.acknowledgeAll(context)
    }
}
