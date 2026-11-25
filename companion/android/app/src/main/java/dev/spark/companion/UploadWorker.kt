package dev.spark.companion

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class UploadWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val settings = SettingsStore(applicationContext)
        if (!settings.isConfigured()) {
            return@withContext Result.success()
        }
        val pending = Uploader.pending(applicationContext)
        if (pending.isEmpty()) {
            return@withContext Result.success()
        }

        val delivered = mutableSetOf<String>()
        var unauthorized = false
        for (item in pending) {
            val result = SparkApi.postNotification(
                settings.backendUrl,
                settings.deviceToken,
                item,
            )
            if (result.ok) {
                delivered.add(item.optString("client_event_id"))
            } else if (result.status == 401 || result.status == 403) {
                unauthorized = true
                break
            }
        }
        Uploader.remove(applicationContext, delivered)

        when {
            unauthorized -> Result.failure()
            Uploader.pending(applicationContext).isEmpty() -> Result.success()
            else -> Result.retry()
        }
    }
}
