import { useEffect, useMemo, useRef, useState } from "react";
import { api, getOwnerToken, setOwnerToken } from "../api";
import { speakText } from "../voice";
import {
  BellIcon,
  CalendarIcon,
  CheckIcon,
  CopyIcon,
  ExternalIcon,
  FileIcon,
  GlobeIcon,
  MailIcon,
  PhoneIcon,
  RefreshIcon,
  ShieldIcon,
  SparkIcon,
  VolumeIcon,
  WhatsAppIcon,
  XIcon,
} from "../icons";

const PROFILE_FIELDS = [
  ["name", "Full name", "text"],
  ["email", "Email", "email"],
  ["phone", "Phone", "tel"],
  ["college", "College / University", "text"],
  ["course", "Course", "text"],
  ["branch", "Branch", "text"],
  ["graduation_year", "Graduation year", "text"],
  ["dob", "Date of birth", "date"],
  ["address", "Address", "text"],
  ["city", "City", "text"],
  ["state", "State", "text"],
  ["pincode", "PIN code", "text"],
  ["linkedin", "LinkedIn", "url"],
  ["github", "GitHub", "url"],
  ["portfolio", "Portfolio", "url"],
  ["skills", "Skills", "text"],
  ["summary", "Short bio", "textarea"],
];

function formatTime(iso, language) {
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat(language === "hi" ? "hi-IN" : "en-IN", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function permissionLabel(t, permission) {
  if (permission === "granted") return t.permissionGranted;
  if (permission === "denied") return t.permissionDenied;
  return t.permissionDefault;
}

export function SettingsView({
  t,
  language,
  config,
  showToast,
  onChanged,
  onConnect,
  onDisconnect,
  onEnableNotifications,
  notificationPermission,
}) {
  const capabilities = config?.capabilities || {};
  const google = config?.google || {};
  const voice = config?.voice || {};
  const llm = config?.llm || {};
  const sync = config?.sync || {};

  const [profile, setProfile] = useState(config?.profile || {});
  const [devices, setDevices] = useState([]);
  const [formsStats, setFormsStats] = useState({ analyzed: 0, submitted: 0 });
  const [deviceName, setDeviceName] = useState("Android phone");
  const [paired, setPaired] = useState(null);
  const [pairing, setPairing] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [testing, setTesting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [token, setToken] = useState(getOwnerToken());
  const [copied, setCopied] = useState(false);
  const fileRef = useRef(null);

  useEffect(() => {
    setProfile(config?.profile || {});
  }, [config?.profile]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [deviceResult, statsResult] = await Promise.allSettled([
        api.get("/api/companion/devices"),
        api.get("/api/forms/stats"),
      ]);
      if (cancelled) return;
      if (deviceResult.status === "fulfilled") setDevices(deviceResult.value.devices || []);
      if (statsResult.status === "fulfilled") setFormsStats(statsResult.value);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const lastSync = useMemo(
    () => formatTime(sync.last_sync, language) || t.never,
    [language, sync.last_sync, t.never],
  );

  async function saveProfile(event) {
    event.preventDefault();
    setSavingProfile(true);
    try {
      const result = await api.put("/api/profile", profile);
      setProfile(result.profile || profile);
      showToast(t.saved, "good");
      onChanged?.();
    } catch {
      showToast(t.error, "bad");
    } finally {
      setSavingProfile(false);
    }
  }

  async function syncNow() {
    setSyncing(true);
    try {
      const result = await api.post("/api/sync");
      if (result.ok) {
        showToast(
          language === "hi"
            ? `${result.new_messages} नए संदेश, ${result.new_deadlines} डेडलाइन।`
            : `${result.new_messages} new messages, ${result.new_deadlines} deadlines.`,
          "good",
        );
      } else {
        showToast(result.reason || t.demoMode, "neutral");
      }
      onChanged?.();
    } catch {
      showToast(t.error, "bad");
    } finally {
      setSyncing(false);
    }
  }

  async function pairDevice() {
    setPairing(true);
    setCopied(false);
    try {
      const result = await api.post("/api/companion/pair", {
        name: deviceName || "Android phone",
        platform: "android",
      });
      setPaired(result);
      const listing = await api.get("/api/companion/devices");
      setDevices(listing.devices || []);
    } catch {
      showToast(t.error, "bad");
    } finally {
      setPairing(false);
    }
  }

  async function revokeDevice(id) {
    try {
      await api.delete(`/api/companion/devices/${id}`);
      setDevices((prev) => prev.filter((device) => device.id !== id));
      showToast(t.saved, "neutral");
    } catch {
      showToast(t.error, "bad");
    }
  }

  async function copyToken() {
    if (!paired?.token) return;
    try {
      await navigator.clipboard.writeText(paired.token);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  async function importExport(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const text = await file.text();
      const result = await api.post("/api/whatsapp/import", {
        text,
        filename: file.name,
      });
      showToast(
        t.imported
          .replace("{stored}", result.stored)
          .replace("{deadlines}", result.deadlines),
        "good",
      );
      onChanged?.();
    } catch {
      showToast(t.error, "bad");
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function testVoice() {
    setTesting(true);
    try {
      await speakText({
        text: t.voiceTestText,
        language,
        useServerTTS: voice.tts && voice.tts !== "browser",
      });
    } catch {
      showToast(t.voiceUnsupported, "bad");
    } finally {
      setTesting(false);
    }
  }

  function saveToken() {
    setOwnerToken(token.trim());
    showToast(token.trim() ? t.tokenSaved : t.tokenCleared, "good");
    onChanged?.();
  }

  return (
    <div className="page settings-page">
      <header className="page-head">
        <div>
          <p className="eyebrow">{language === "hi" ? "कॉन्फ़िगरेशन" : "Configuration"}</p>
          <h1>{t.settingsTitle}</h1>
          <p>{t.settingsSub}</p>
        </div>
        <span className={`mode-chip ${capabilities.mode || "demo"}`}>
          <span className="dot" />
          {capabilities.mode === "live" ? t.liveMode : t.demoMode}
        </span>
      </header>

      <div className="settings-grid">
        <section className="panel settings-card">
          <header className="settings-head">
            <span className="settings-icon">
              <GlobeIcon size={18} />
            </span>
            <div>
              <h2>{t.connectionTitle}</h2>
              <p>{t.connectionSub}</p>
            </div>
          </header>

          <div className="settings-row">
            <span className={`status-dot ${google.connected ? "good" : "warn"}`} />
            <div className="settings-row-main">
              <strong>
                {google.connected ? t.googleConnectedLabel : t.googleDisconnectedLabel}
              </strong>
              <span>
                {google.connected
                  ? language === "hi"
                    ? "Gmail, Calendar और Drive लाइव हैं।"
                    : "Gmail, Calendar and Drive are live."
                  : t.googleSetupHint}
              </span>
            </div>
            {google.configured ? (
              <button
                type="button"
                className={google.connected ? "btn subtle" : "btn primary"}
                onClick={google.connected ? onDisconnect : onConnect}
              >
                {google.connected ? t.disconnect : t.connectGoogle}
              </button>
            ) : (
              <span className="tag warn">{language === "hi" ? "कॉन्फ़िगर नहीं" : "Not configured"}</span>
            )}
          </div>

          <div className="settings-row">
            <span className="settings-icon small">
              <MailIcon size={15} />
            </span>
            <div className="settings-row-main">
              <strong>{t.syncNow}</strong>
              <span>
                {t.lastSync}: {lastSync}
                {sync.last_error ? ` · ${String(sync.last_error).slice(0, 90)}` : ""}
              </span>
            </div>
            <button type="button" className="btn ghost" onClick={syncNow} disabled={syncing}>
              <RefreshIcon size={15} />
              {syncing ? t.syncing : t.refresh}
            </button>
          </div>

          <div className="capability-grid">
            {[
              ["calendar", CalendarIcon, "Calendar"],
              ["gmail", MailIcon, "Gmail"],
              ["drive", FileIcon, "Drive"],
              ["reminders", BellIcon, "Reminders"],
              ["forms", SparkIcon, "Forms"],
              ["companion", PhoneIcon, "WhatsApp"],
            ].map(([key, Icon, label]) => (
              <span key={key} className={`capability-tile ${capabilities[key] ? "on" : ""}`}>
                <Icon size={15} />
                <span>{label}</span>
                <em>{String(capabilities[key] || "off")}</em>
              </span>
            ))}
          </div>

          <div className="settings-note">
            <SparkIcon size={14} />
            <span>
              {llm.provider === "local-planner"
                ? language === "hi"
                  ? "LLM कुंजी नहीं है — लोकल प्लानर चल रहा है।"
                  : "No LLM key — the deterministic local planner is running."
                : `${llm.provider} · ${llm.model}`}
              {" · "}
              {voice.tts === "browser" ? t.voiceBrowser : `TTS: ${voice.tts}`}
              {" · "}
              {voice.stt === "browser" ? t.voiceBrowser : `STT: ${voice.stt}`}
            </span>
          </div>
        </section>

        <section className="panel settings-card">
          <header className="settings-head">
            <span className="settings-icon whatsapp">
              <WhatsAppIcon size={18} />
            </span>
            <div>
              <h2>{t.companionTitle}</h2>
              <p>{t.companionSub}</p>
            </div>
          </header>

          <div className="pair-row">
            <label className="field-inline">
              <span>{t.deviceName}</span>
              <input
                type="text"
                value={deviceName}
                onChange={(event) => setDeviceName(event.target.value)}
                maxLength={80}
              />
            </label>
            <button type="button" className="btn primary" onClick={pairDevice} disabled={pairing}>
              <PhoneIcon size={15} />
              {pairing ? t.pairing : t.pairDevice}
            </button>
          </div>

          {paired?.token && (
            <div className="token-box">
              <div>
                <strong>{t.pairingToken}</strong>
                <code>{paired.token}</code>
                <small>{paired.endpoint}</small>
              </div>
              <button type="button" className="mini-btn" onClick={copyToken}>
                {copied ? <CheckIcon size={13} /> : <CopyIcon size={13} />}
                {copied ? t.copied : t.copy}
              </button>
            </div>
          )}

          <div className="device-list">
            <span className="side-label">{t.pairedDevices}</span>
            {devices.length === 0 ? (
              <p className="muted-small">{t.noDevices}</p>
            ) : (
              devices.map((device) => (
                <div className="device-row" key={device.id}>
                  <span className="device-icon">
                    <PhoneIcon size={15} />
                  </span>
                  <div>
                    <strong>{device.name}</strong>
                    <span>
                      {device.platform || "android"}
                      {device.last_seen ? ` · ${formatTime(device.last_seen, language)}` : ""}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="mini-btn bad"
                    onClick={() => revokeDevice(device.id)}
                  >
                    <XIcon size={12} />
                    {t.revoke}
                  </button>
                </div>
              ))
            )}
          </div>

          <div className="import-row">
            <div>
              <strong>{t.exportTitle}</strong>
              <p>{t.exportSub}</p>
            </div>
            <input
              ref={fileRef}
              type="file"
              accept=".txt,text/plain"
              className="hidden-input"
              onChange={importExport}
            />
            <button
              type="button"
              className="btn ghost"
              onClick={() => fileRef.current?.click()}
              disabled={importing}
            >
              <FileIcon size={15} />
              {importing ? t.importing : t.importExport}
            </button>
          </div>

          <a
            className="settings-link"
            href="https://github.com/KHarinadhReddy/Spark/tree/main/companion/android"
            target="_blank"
            rel="noreferrer"
          >
            <ExternalIcon size={13} />
            {language === "hi" ? "Android साथी इंस्टॉल करें" : "Install the Android companion"}
          </a>
        </section>

        <section className="panel settings-card wide">
          <header className="settings-head">
            <span className="settings-icon">
              <SparkIcon size={18} />
            </span>
            <div>
              <h2>{t.profileTitle}</h2>
              <p>{t.profileSub}</p>
            </div>
          </header>

          <form className="profile-form" onSubmit={saveProfile}>
            {PROFILE_FIELDS.map(([key, label, type]) => (
              <label key={key} className={`field-inline ${type === "textarea" ? "wide" : ""}`}>
                <span>{label}</span>
                {type === "textarea" ? (
                  <textarea
                    rows={3}
                    value={profile[key] || ""}
                    onChange={(event) =>
                      setProfile((prev) => ({ ...prev, [key]: event.target.value }))
                    }
                  />
                ) : (
                  <input
                    type={type}
                    value={profile[key] || ""}
                    onChange={(event) =>
                      setProfile((prev) => ({ ...prev, [key]: event.target.value }))
                    }
                  />
                )}
              </label>
            ))}
            <div className="profile-actions">
              <button type="submit" className="btn primary" disabled={savingProfile}>
                <CheckIcon size={15} />
                {savingProfile ? t.saving : t.saveProfile}
              </button>
              <span className="muted-small">
                {language === "hi"
                  ? "सिर्फ़ फ़ॉर्म भरने के लिए इस्तेमाल होता है।"
                  : "Used only for forms you review."}
              </span>
            </div>
          </form>
        </section>

        <section className="panel settings-card">
          <header className="settings-head">
            <span className="settings-icon">
              <VolumeIcon size={18} />
            </span>
            <div>
              <h2>{t.voiceTitle}</h2>
              <p>{t.voiceSub}</p>
            </div>
          </header>

          <div className="settings-row">
            <div className="settings-row-main">
              <strong>{voice.tts === "browser" ? t.voiceBrowser : t.voiceServer}</strong>
              <span>
                TTS: {voice.tts || "browser"} · STT: {voice.stt || "browser"}
              </span>
            </div>
            <button type="button" className="btn ghost" onClick={testVoice} disabled={testing}>
              <VolumeIcon size={15} />
              {testing ? t.testingVoice : t.testVoice}
            </button>
          </div>

          <div className="settings-row">
            <div className="settings-row-main">
              <strong>{t.sttTitle}</strong>
              <span>
                {voice.stt === "browser"
                  ? language === "hi"
                    ? "ब्राउज़र स्पीच रिकग्निशन"
                    : "Browser speech recognition"
                  : voice.stt === "groq-whisper"
                    ? "Groq Whisper (free tier)"
                    : "ElevenLabs Scribe"}
              </span>
            </div>
            <span className={`tag ${voice.stt_available ? "good" : ""}`}>
              {voice.stt_available ? "ready" : "fallback"}
            </span>
          </div>

          <div className="settings-row">
            <div className="settings-row-main">
              <strong>{t.notificationsPermission}</strong>
              <span>{permissionLabel(t, notificationPermission)}</span>
            </div>
            <button
              type="button"
              className="btn subtle"
              onClick={onEnableNotifications}
              disabled={notificationPermission === "granted"}
            >
              <BellIcon size={14} />
              {t.enableNotifications}
            </button>
          </div>
          <p className="muted-small">{t.notificationsHint}</p>
        </section>

        <section className="panel settings-card">
          <header className="settings-head">
            <span className="settings-icon">
              <FileIcon size={18} />
            </span>
            <div>
              <h2>{t.formsTitle}</h2>
              <p>{t.formsSub}</p>
            </div>
          </header>

          <div className="stat-pair">
            <div>
              <strong>{formsStats.analyzed || 0}</strong>
              <span>{t.formsAnalyzed}</span>
            </div>
            <div>
              <strong>{formsStats.submitted || 0}</strong>
              <span>{t.formsSubmitted}</span>
            </div>
          </div>
          <p className="muted-small">
            {language === "hi"
              ? "एक्सटेंशन फ़ॉर्म भरता है; सबमिट से पहले आपको हर फ़ील्ड दिखती है।"
              : "The extension fills the form; you see every field before the final submit."}
          </p>
          <a
            className="settings-link"
            href="https://github.com/KHarinadhReddy/Spark/tree/main/extension"
            target="_blank"
            rel="noreferrer"
          >
            <ExternalIcon size={13} />
            {language === "hi" ? "Chrome एक्सटेंशन देखें" : "View the Chrome extension"}
          </a>
        </section>

        <section className="panel settings-card">
          <header className="settings-head">
            <span className="settings-icon">
              <ShieldIcon size={18} />
            </span>
            <div>
              <h2>{t.securityTitle}</h2>
              <p>{t.securitySub}</p>
            </div>
          </header>

          <label className="field-inline">
            <span>{t.ownerToken}</span>
            <input
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder={t.ownerTokenPlaceholder}
              autoComplete="off"
            />
          </label>
          <div className="profile-actions">
            <button type="button" className="btn primary" onClick={saveToken}>
              <CheckIcon size={15} />
              {t.saveToken}
            </button>
            {token && (
              <button
                type="button"
                className="btn subtle"
                onClick={() => {
                  setToken("");
                  setOwnerToken("");
                  showToast(t.tokenCleared, "neutral");
                  onChanged?.();
                }}
              >
                {t.disconnect}
              </button>
            )}
          </div>
          <p className="muted-small">{t.tokenHint}</p>
        </section>
      </div>

      <footer className="page-footer">
        <span>
          <ShieldIcon size={14} />
          {language === "hi"
            ? "हर राइट ऑपरेशन अप्रूवल गेट और ऑडिट लॉग से गुज़रता है।"
            : "Every write passes through the approval gate and audit log."}
        </span>
        <span className="footer-dot">·</span>
        <span>{t.footerNote}</span>
      </footer>
    </div>
  );
}
