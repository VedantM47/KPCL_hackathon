package com.kpcl.plantalert

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView

/** Colours and view builders shared by every screen (the app builds its views in code, no XML layouts). */
class Ui(private val c: Context) {
    companion object {
        val BRAND = Color.parseColor("#0F3D5E")
        val BRAND_LIGHT = Color.parseColor("#1E6A99")
        val PAGE = Color.parseColor("#F3F6F9")
        val GREEN = Color.parseColor("#2E7D32")
        val RED = Color.parseColor("#C62828")
        val ORANGE = Color.parseColor("#EF6C00")
        val GREY = Color.parseColor("#6B7C8A")
        val LINE = Color.parseColor("#DDE4EA")
        val INK = Color.parseColor("#1B2733")
        val TEAL = Color.parseColor("#2A9D8F")
    }

    fun dp(v: Int) = (v * c.resources.displayMetrics.density).toInt()

    fun shape(color: Int, radiusDp: Int, stroke: Int? = null) = GradientDrawable().apply {
        setColor(color)
        cornerRadius = dp(radiusDp).toFloat()
        if (stroke != null) setStroke(dp(1), stroke)
    }

    fun text(t: String, size: Float = 14f, color: Int = INK, bold: Boolean = false, alpha: Float = 1f) =
        TextView(c).apply {
            text = t
            textSize = size
            setTextColor(color)
            this.alpha = alpha
            if (bold) setTypeface(typeface, Typeface.BOLD)
        }

    fun mono(t: String, size: Float = 12f, color: Int = INK) = text(t, size, color).apply { typeface = Typeface.MONOSPACE }

    fun card() = LinearLayout(c).apply {
        orientation = LinearLayout.VERTICAL
        background = shape(Color.WHITE, 14)
        setPadding(dp(16), dp(14), dp(16), dp(16))
        elevation = dp(2).toFloat()
    }

    fun vertical() = LinearLayout(c).apply { orientation = LinearLayout.VERTICAL }

    fun horizontal() = LinearLayout(c).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
    }

    fun lp(top: Int = 0, bottom: Int = 0, w: Int = -1, h: Int = -2) =
        LinearLayout.LayoutParams(w, h).apply { topMargin = dp(top); bottomMargin = dp(bottom) }

    fun weight(left: Int = 0, right: Int = 0) =
        LinearLayout.LayoutParams(0, -2, 1f).apply { leftMargin = dp(left); rightMargin = dp(right) }

    fun solidButton(label: String, color: Int, size: Float = 15f) = Button(c).apply {
        text = label
        isAllCaps = true
        setTextColor(Color.WHITE)
        textSize = size
        setTypeface(typeface, Typeface.BOLD)
        background = shape(color, 12)
        stateListAnimator = null
        minHeight = dp(52)
    }

    fun outlineButton(label: String, color: Int = BRAND) = Button(c).apply {
        text = label
        isAllCaps = false
        setTextColor(color)
        textSize = 13f
        background = shape(Color.WHITE, 12, color)
        stateListAnimator = null
        minHeight = dp(46)
    }

    fun fieldLabel(t: String) = text(t, 11f, GREY, true).apply { setPadding(0, dp(12), 0, dp(2)) }

    /** Brand header bar with the logo, a title and an optional subtitle. */
    fun header(title: String, subtitle: String): LinearLayout {
        val h = horizontal().apply {
            setBackgroundColor(BRAND)
            setPadding(dp(18), dp(14), dp(18), dp(18))
        }
        h.addView(ImageView(c).apply {
            setImageResource(R.drawable.ic_logo)
            setPadding(dp(6), dp(6), dp(6), dp(6))
            background = shape(BRAND_LIGHT, 14)
        }, LinearLayout.LayoutParams(dp(46), dp(46)).apply { rightMargin = dp(12) })
        val titles = vertical()
        titles.addView(text(title, 21f, Color.WHITE, true))
        titles.addView(text(subtitle, 12f, Color.WHITE, alpha = 0.75f))
        h.addView(titles, LinearLayout.LayoutParams(0, -2, 1f))
        return h
    }
}
