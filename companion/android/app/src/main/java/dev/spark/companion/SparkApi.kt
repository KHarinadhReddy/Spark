package dev.spark.companion

import org.json.JSONObject
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL

data class ApiResult(
    val ok: Boolean,
    val status: Int,
    val message: String,
)

object SparkApi {
    fun test(backendUrl: String, token: String): ApiResult {
        if (!backendUrl.startsWith("http")) {
            return ApiResult(false, 0, "Backend URL must start with http:// or https://")
        }
        return request(
            url = "${backendUrl.trimEnd('/')}/api/companion/me",
            method = "GET",
            token = token,
            body = null,
        )
    }

    fun postNotification(backendUrl: String, token: String, payload: JSONObject): ApiResult {
        return request(
            url = "${backendUrl.trimEnd('/')}/api/companion/notifications",
            method = "POST",
            token = token,
            body = payload.toString(),
        )
    }

    private fun request(
        url: String,
        method: String,
        token: String,
        body: String?,
    ): ApiResult {
        var connection: HttpURLConnection? = null
        return try {
            connection = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod = method
                connectTimeout = 15_000
                readTimeout = 30_000
                setRequestProperty("Accept", "application/json")
                if (token.isNotBlank()) {
                    setRequestProperty("x-spark-device", token)
                }
                if (body != null) {
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                }
            }
            if (body != null) {
                connection.outputStream.use { stream ->
                    stream.write(body.toByteArray(Charsets.UTF_8))
                }
            }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use(BufferedReader::readText).orEmpty()
            val message = if (text.isBlank()) {
                if (status in 200..299) "OK" else "HTTP $status"
            } else {
                runCatching { JSONObject(text).optString("detail", text) }.getOrDefault(text)
            }
            ApiResult(status in 200..299, status, message.take(300))
        } catch (error: Exception) {
            ApiResult(false, 0, error.message ?: error.javaClass.simpleName)
        } finally {
            connection?.disconnect()
        }
    }
}
