package dev.spark.companion

import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {

    private lateinit var settings: SettingsStore
    private lateinit var backendUrl: EditText
    private lateinit var deviceToken: EditText
    private lateinit var accessStatus: TextView
    private lateinit var connectionStatus: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        settings = SettingsStore(this)

        backendUrl = findViewById(R.id.backendUrl)
        deviceToken = findViewById(R.id.deviceToken)
        accessStatus = findViewById(R.id.accessStatus)
        connectionStatus = findViewById(R.id.connectionStatus)

        backendUrl.setText(settings.backendUrl)
        deviceToken.setText(settings.deviceToken)

        findViewById<Button>(R.id.save).setOnClickListener { save() }
        findViewById<Button>(R.id.test).setOnClickListener { testConnection() }
        findViewById<Button>(R.id.openAccess).setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
    }

    override fun onResume() {
        super.onResume()
        updateAccessStatus()
    }

    private fun save() {
        val url = backendUrl.text.toString().trim().trimEnd('/')
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            connectionStatus.text = getString(R.string.status_error, "URL must start with http:// or https://")
            return
        }
        settings.backendUrl = url
        settings.deviceToken = deviceToken.text.toString().trim()
        connectionStatus.text = getString(R.string.status_saved)
        connectionStatus.setTextColor(ContextCompat.getColor(this, R.color.spark_good))
        if (settings.isConfigured()) {
            // Retry anything queued while the URL or token was wrong.
            Uploader.schedule(this)
        }
    }

    private fun testConnection() {
        save()
        if (!settings.isConfigured()) {
            connectionStatus.text = getString(R.string.status_need_config)
            connectionStatus.setTextColor(ContextCompat.getColor(this, R.color.spark_muted))
            return
        }
        connectionStatus.text = getString(R.string.status_checking)
        val url = settings.backendUrl
        val token = settings.deviceToken
        Thread {
            val result = SparkApi.test(url, token)
            runOnUiThread {
                if (result.ok) {
                    connectionStatus.text = getString(R.string.status_ready)
                    connectionStatus.setTextColor(ContextCompat.getColor(this, R.color.spark_good))
                } else {
                    connectionStatus.text = getString(R.string.status_error, result.message)
                    connectionStatus.setTextColor(ContextCompat.getColor(this, R.color.spark_error))
                }
            }
        }.start()
    }

    private fun updateAccessStatus() {
        val enabled = NotificationManagerCompat.getEnabledListenerPackages(this)
            .contains(packageName)
        if (enabled) {
            accessStatus.text = getString(R.string.status_access_on)
            accessStatus.setTextColor(ContextCompat.getColor(this, R.color.spark_good))
        } else {
            accessStatus.text = getString(R.string.status_access_missing)
            accessStatus.setTextColor(ContextCompat.getColor(this, R.color.spark_warning))
        }
    }
}
