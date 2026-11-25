package dev.spark.companion

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.TimeUnit

/**
 * Durable, best-effort upload queue.
 *
 * A notification is written to SharedPreferences before any network call, so a
 * process death or a dead zone does not lose it. WorkManager retries with
 * exponential backoff when the phone is online again.
 */
object Uploader {
    private const val PREFS = "spark_companion_queue"
    private const val KEY = "queue"
    private const val LIMIT = 500
    private const val WORK = "spark-companion-upload"
    private val lock = Any()

    fun enqueue(context: Context, payload: JSONObject) {
        payload.put("client_event_id", UUID.randomUUID().toString())
        synchronized(lock) {
            val queue = read(context)
            while (queue.length() >= LIMIT) {
                queue.remove(0)
            }
            queue.put(payload)
            write(context, queue)
        }
        schedule(context)
    }

    fun pending(context: Context): List<JSONObject> = synchronized(lock) {
        val queue = read(context)
        buildList {
            for (index in 0 until queue.length()) {
                queue.optJSONObject(index)?.let { add(it) }
            }
        }
    }

    fun remove(context: Context, ids: Set<String>) {
        if (ids.isEmpty()) return
        synchronized(lock) {
            val queue = read(context)
            val remaining = JSONArray()
            for (index in 0 until queue.length()) {
                val item = queue.optJSONObject(index) ?: continue
                if (item.optString("client_event_id") !in ids) {
                    remaining.put(item)
                }
            }
            write(context, remaining)
        }
    }

    fun schedule(context: Context) {
        val request = OneTimeWorkRequestBuilder<UploadWorker>()
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context.applicationContext)
            .enqueueUniqueWork(WORK, ExistingWorkPolicy.REPLACE, request)
    }

    private fun read(context: Context): JSONArray {
        val raw = context.applicationContext
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY, null)
        return try {
            if (raw.isNullOrBlank()) JSONArray() else JSONArray(raw)
        } catch (_: Exception) {
            JSONArray()
        }
    }

    private fun write(context: Context, queue: JSONArray) {
        context.applicationContext
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY, queue.toString())
            .apply()
    }
}
