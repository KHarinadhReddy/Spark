package dev.spark.companion

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONObject

/**
 * Captures WhatsApp notifications while the app is closed or in the background.
 *
 * Android only exposes notification content, never the full chat history. This
 * service is read-only: Spark cannot send WhatsApp messages.
 */
class SparkNotificationListener : NotificationListenerService() {

    private val recent = LinkedHashMap<String, Long>()

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        val status = sbn ?: return
        if (status.packageName !in WHATSAPP_PACKAGES) return
        val notification = status.notification ?: return
        if (notification.flags and Notification.FLAG_GROUP_SUMMARY != 0) return

        val extras = notification.extras ?: return
        val title = (
            extras.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE)
                ?: extras.getCharSequence(Notification.EXTRA_TITLE)
            )?.toString()?.trim().orEmpty()
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()?.trim().orEmpty()
        val bigText = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()?.trim().orEmpty()
        val subText = extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString()?.trim().orEmpty()
        if (title.isBlank() && text.isBlank() && bigText.isBlank()) return

        val dedupeKey = "${status.packageName}|$title|${text.ifBlank { bigText }}"
        val now = System.currentTimeMillis()
        synchronized(recent) {
            val last = recent[dedupeKey]
            if (last != null && now - last < 30_000) return
            recent[dedupeKey] = now
            if (recent.size > 80) {
                val cutoff = now - 5 * 60_000
                val iterator = recent.entries.iterator()
                while (iterator.hasNext()) {
                    if (iterator.next().value < cutoff) iterator.remove()
                }
            }
        }

        val payload = JSONObject().apply {
            put("package", status.packageName)
            put("app", appLabel(status.packageName))
            put("title", title)
            put("text", text.ifBlank { bigText })
            put("big_text", bigText)
            put("subtext", subText)
            put("timestamp", status.postTime)
        }
        Uploader.enqueue(applicationContext, payload)
    }

    private fun appLabel(packageName: String): String {
        return try {
            val info = packageManager.getApplicationInfo(packageName, 0)
            packageManager.getApplicationLabel(info).toString()
        } catch (_: Exception) {
            "WhatsApp"
        }
    }

    companion object {
        private val WHATSAPP_PACKAGES = setOf(
            "com.whatsapp",
            "com.whatsapp.w4b",
        )
    }
}
