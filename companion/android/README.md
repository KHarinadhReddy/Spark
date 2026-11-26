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

The debug APK lands at `app/build/outputs/apk/debug/app-debug.apk`. Install it
with `adb install -r app/build/outputs/apk/debug/app-debug.apk`, or open the
project in Android Studio and press Run.

### Signed release build

The installable build on the phone should be a release APK. Create a local
keystore once (never commit it):

```bash
keytool -genkeypair -v -keystore spark-release.keystore -alias spark \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -dname "CN=Spark Companion, O=Spark, C=IN"
```

Create `companion/android/keystore.properties` (gitignored):

```properties
storeFile=spark-release.keystore
storePassword=...
keyAlias=spark
keyPassword=...
```

Then build:

```bash
.\gradlew.bat assembleRelease
```

The signed APK lands at
`app/build/outputs/apk/release/app-release.apk`. `targetSdk` is 36, matching
Android 16, while `compileSdk` stays on 37.

Both debug and release builds allow cleartext HTTP so the phone can reach a
LAN backend such as `http://10.10.35.232:8000`. Keep the backend on HTTPS for
a public deployment, and rotate the access password before exposing it.


## Pair it

1. In Spark, open **Settings → WhatsApp companion**.
2. Name the phone and press **Pair a device**.
3. Copy the device token (shown once).
4. Install the APK, open **Spark Companion**, and enter:
   - **Backend URL** — e.g. `http://10.10.35.232:8000` on the same Wi-Fi, or
     `https://spark.example.com` for a public deployment.
   - **Device token** — the token from step 3.
5. Press **Save**, then **Test connection**. It calls `/api/companion/me` and
   only succeeds when the token is valid.
6. Press **Open notification access**, find **Spark Companion**, and allow it.
7. Send yourself a WhatsApp message. It should appear in Spark's Inbox within a
   few seconds.

### Installing on Android 16 / ColorOS

WhatsApp refuses `.apk` attachments. Send a ZIP containing the APK instead,
then extract it on the phone with File Manager. On Oppo/ColorOS phones:

1. Allow **Install unknown apps** for Files/Chrome/WhatsApp
   (Settings → Security & privacy → Install unknown apps).
2. Turn off **Pure Mode** (Settings search → “Pure Mode”). It blocks every
   sideloaded app until disabled.
3. If Play Protect warns about an unknown developer, choose
   **More details → Install anyway**.
4. Uninstall any earlier Spark Companion first — a different signing key
   cannot upgrade over it.


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
| `App not installed` | Uninstall any older Spark Companion (different signature), then retry |
| ColorOS blocks the install | Turn off **Pure Mode** and allow **Install unknown apps** for the file manager |
| `Cleartext HTTP not permitted` | Use `http://` only for the debug/LAN setup; public deployments need HTTPS |

## Files

| File | Purpose |
|---|---|
| `SparkNotificationListener.kt` | Receives WhatsApp notifications |
| `Uploader.kt` | SharedPreferences-backed queue + WorkManager scheduling |
| `UploadWorker.kt` | Retries uploads while offline |
| `SparkApi.kt` | Minimal `HttpURLConnection` JSON client |
| `SettingsStore.kt` | Backend URL + device token storage |
| `MainActivity.kt` | Pairing/setup UI |
