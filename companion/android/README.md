# Spark Companion (Android)

The companion forwards **WhatsApp notifications** to your Spark backend, so
Spark can surface and classify them even when the Spark web app is closed. It
is read-only: Spark cannot read chat history and cannot send WhatsApp messages.

## How it works

1. You grant **Notification access** in Android Settings.
2. `SparkNotificationListener` receives WhatsApp notification titles/text.
3. `Uploader` writes each event to a durable local queue first.
4. `WorkManager` uploads the queue to
   `POST /api/companion/notifications` with the device token.
5. Spark classifies the message, detects deadlines, and creates in-app
   notifications.

Only `com.whatsapp` and `com.whatsapp.w4b` are captured. Group summaries are
skipped. Duplicate notifications within 30 seconds are ignored. If the phone is
offline, up to 500 events wait in the queue and retry with backoff.

## Build

Requirements: Android Studio (or JDK 17+ and the Android SDK), Android 8.0+
(API 26).

```bash
cd companion/android
./gradlew assembleDebug        # macOS/Linux
.\gradlew.bat assembleDebug    # Windows PowerShell
```

The APK lands at `app/build/outputs/apk/debug/app-debug.apk`. Install it with
`adb install -r app/build/outputs/apk/debug/app-debug.apk`, or open the project
in Android Studio and press Run.

Debug builds allow cleartext HTTP so you can test against
`http://10.0.2.2:8000` from the emulator. Release builds use Android's default
HTTPS-only policy.

The checked-in Gradle wrapper pins Gradle 9.6.0; AGP 9.4.1 and compileSdk 37
match current Android Studio. If your SDK is older, install SDK Platform 37 or
lower `compileSdk`/`targetSdk` in `app/build.gradle.kts`.

## Pair it

1. In Spark, open **Settings → WhatsApp companion**.
2. Name the phone and press **Pair a device**.
3. Copy the device token (shown once).
4. Install the APK, open **Spark Companion**, and enter:
   - **Backend URL** — e.g. `https://spark.example.com` (must be HTTPS for a
     public deployment; `http://10.0.2.2:8000` works from the emulator against
     a local backend).
   - **Device token** — the token from step 3.
5. Press **Save**, then **Test connection**. It calls `/api/companion/me` and
   only succeeds when the token is valid.
6. Press **Open notification access**, find **Spark Companion**, and allow it.
7. Send yourself a WhatsApp message. It should appear in Spark's Inbox within a
   few seconds.

If the backend has an owner token, pairing already requires it; the companion
itself only uses the device token. Revoke a lost phone from **Settings → Paired
devices** (or `DELETE /api/companion/devices/{id}`).

## Privacy and limits

- Android exposes only notification content, not historical chats. Import a
  WhatsApp chat export in Spark if you want older messages.
- The app does not request WhatsApp account access and uses no unofficial
  WhatsApp bridge.
- Message text is stored in Spark's SQLite database until the retention window
  (`SPARK_RETENTION_DAYS`, default 180 days) purges it.
- The notification text is sent over HTTPS to your own backend only.
- Do not use this to capture other people's notifications without consent.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Test connection says `401` | Re-copy the device token; pairing tokens are shown once |
| No messages arrive | Notification access is off, or battery optimisation killed the listener |
| Works on Wi-Fi only | Use the public HTTPS URL, not `localhost` |
| Duplicate entries | Spark de-duplicates by notification content + timestamp; near-identical reposts can still appear |
| `Cleartext HTTP not permitted` | You are running a release build or a non-local URL over HTTP; use HTTPS (debug builds allow local HTTP) |

## Files

| File | Purpose |
|---|---|
| `SparkNotificationListener.kt` | Receives WhatsApp notifications |
| `Uploader.kt` | SharedPreferences-backed queue + WorkManager scheduling |
| `UploadWorker.kt` | Retries uploads while offline |
| `SparkApi.kt` | Minimal `HttpURLConnection` JSON client |
| `SettingsStore.kt` | Backend URL + device token storage |
| `MainActivity.kt` | Pairing/setup UI |
