package dev.spark.companion

import android.content.Context

class SettingsStore(context: Context) {
    private val prefs = context.applicationContext
        .getSharedPreferences("spark_companion", Context.MODE_PRIVATE)

    var backendUrl: String
        get() = prefs.getString("backend_url", "").orEmpty().trimEnd('/')
        set(value) = prefs.edit().putString("backend_url", value.trim().trimEnd('/')).apply()

    var deviceToken: String
        get() = prefs.getString("device_token", "").orEmpty()
        set(value) = prefs.edit().putString("device_token", value.trim()).apply()

    fun isConfigured(): Boolean = backendUrl.startsWith("http") && deviceToken.isNotBlank()
}
