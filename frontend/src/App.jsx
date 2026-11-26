import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, setOwnerToken } from "./api";
import { COPY } from "./i18n";
import { speakText, startMic, stopSpeech } from "./voice";
import { Sidebar, BottomNav } from "./components/Sidebar";
import { TodayView } from "./components/TodayView";
import { ChatView } from "./components/ChatView";
import { ActivityView } from "./components/ActivityView";
import { InboxView } from "./components/InboxView";
import { DeadlinesView } from "./components/DeadlinesView";
import { SettingsView } from "./components/SettingsView";
import { NotificationsPanel } from "./components/NotificationsPanel";
import { Toast } from "./components/Toast";
import { SparkIcon, GlobeIcon, BellIcon, SettingsIcon, ShieldIcon } from "./icons";

const LANG_KEY = "spark.language";
const VIEW_KEY = "spark.view";
const VIEWS = ["today", "chat", "inbox", "deadlines", "activity", "settings"];

function initialLanguage() {
  try {
    const stored = window.localStorage.getItem(LANG_KEY);
    if (stored === "en" || stored === "hi") return stored;
  } catch {
    // private mode — fall back to English
  }
  return "en";
}

function initialView() {
  try {
    const stored = window.localStorage.getItem(VIEW_KEY);
    if (VIEWS.includes(stored)) return stored;
  } catch {
    // ignore
  }
  return "today";
}

let messageCounter = 0;
function nextId(prefix) {
  messageCounter += 1;
  return `${prefix}-${Date.now().toString(36)}-${messageCounter}`;
}

export default function App() {
  const [language, setLanguage] = useState(initialLanguage);
  const [view, setView] = useState(initialView);
  const [config, setConfig] = useState(null);
  const [brief, setBrief] = useState(null);
  const [briefLoading, setBriefLoading] = useState(true);
  const [actionsMap, setActionsMap] = useState({});
  const [pending, setPending] = useState([]);
  const [audit, setAudit] = useState([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [messages, setMessages] = useState([]);
  const [thinking, setThinking] = useState(false);
  const [actionBusy, setActionBusy] = useState({});
  const [mic, setMic] = useState("idle");
  const [playing, setPlaying] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [toast, setToast] = useState(null);
  const [ready, setReady] = useState(false);
  const [locked, setLocked] = useState(false);
  const [unlock, setUnlock] = useState("");
  const [unlockError, setUnlockError] = useState("");
  const [unlocking, setUnlocking] = useState(false);
  const [inbox, setInbox] = useState([]);
  const [inboxStats, setInboxStats] = useState({});
  const [inboxLoading, setInboxLoading] = useState(false);
  const [deadlines, setDeadlines] = useState([]);
  const [deadlineStatus, setDeadlineStatus] = useState("active");
  const [deadlinesLoading, setDeadlinesLoading] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [unread, setUnread] = useState(0);
  const [notifOpen, setNotifOpen] = useState(false);
  const [notificationPermission, setNotificationPermission] = useState(() =>
    typeof Notification !== "undefined" ? Notification.permission : "unsupported",
  );

  const micRef = useRef(null);
  const lastUnreadRef = useRef(0);
  const t = COPY[language];
  const serverTts = config?.voice?.tts && config.voice.tts !== "browser";
  const serverStt = config?.voice?.stt && config.voice.stt !== "browser";

  const showToast = useCallback((message, tone = "neutral", undoId = null) => {
    setToast({ id: Date.now(), message, tone, undoId });
  }, []);

  const closeToast = useCallback(() => setToast(null), []);

  const mergeActions = useCallback((items) => {
    if (!items?.length) return;
    setActionsMap((prev) => {
      const next = { ...prev };
      items.forEach((action) => {
        next[action.id] = { ...prev[action.id], ...action };
      });
      return next;
    });
  }, []);

  const refreshActions = useCallback(async () => {
    try {
      const payload = await api.get("/api/actions");
      mergeActions([...payload.pending, ...payload.recent]);
      setPending(payload.pending);
      return payload;
    } catch {
      return null;
    }
  }, [mergeActions]);

  const refreshAudit = useCallback(async () => {
    setAuditLoading(true);
    try {
      const payload = await api.get("/api/audit?limit=120");
      setAudit(payload.audit);
      return payload.audit;
    } catch {
      return null;
    } finally {
      setAuditLoading(false);
    }
  }, []);

  const refreshBrief = useCallback(
    async (lang = language) => {
      setBriefLoading(true);
      try {
        const payload = await api.get(`/api/brief?language=${lang}`);
        setBrief(payload);
        return payload;
      } catch {
        return null;
      } finally {
        setBriefLoading(false);
      }
    },
    [language],
  );

  const refreshConfig = useCallback(async () => {
    try {
      const payload = await api.get("/api/config");
      setConfig(payload);
      setLocked(false);
      return payload;
    } catch (error) {
      if (error?.status === 401) setLocked(true);
      return null;
    }
  }, []);

  const refreshInbox = useCallback(async () => {
    setInboxLoading(true);
    try {
      const payload = await api.get("/api/inbox?limit=100");
      setInbox(payload.messages || []);
      setInboxStats(payload.stats || {});
      return payload;
    } catch (error) {
      if (error?.status === 401) {
        showToast(COPY[initialLanguage()].error, "bad");
      }
      return null;
    } finally {
      setInboxLoading(false);
    }
  }, [showToast]);

  const refreshDeadlines = useCallback(
    async (status = deadlineStatus) => {
      setDeadlinesLoading(true);
      try {
        const payload = await api.get(`/api/deadlines?status=${status}`);
        setDeadlines(payload.deadlines || []);
        return payload;
      } catch {
        return null;
      } finally {
        setDeadlinesLoading(false);
      }
    },
    [deadlineStatus],
  );

  const refreshNotifications = useCallback(async () => {
    try {
      const payload = await api.get("/api/notifications?limit=60");
      const items = payload.notifications || [];
      const count = payload.unread || 0;
      setNotifications(items);
      setUnread(count);
      if (
        count > lastUnreadRef.current &&
        lastUnreadRef.current !== 0 &&
        typeof Notification !== "undefined" &&
        Notification.permission === "granted" &&
        document.visibilityState !== "visible"
      ) {
        const latest = items.find((item) => !item.read);
        if (latest) {
          try {
            new Notification(latest.title, {
              body: latest.body || "Spark",
              tag: latest.id,
              icon: "/icons/icon-192.png",
            });
          } catch {
            // browser refused the notification — the in-app badge still updates
          }
        }
      }
      lastUnreadRef.current = count;
      return payload;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    document.documentElement.lang = language === "hi" ? "hi" : "en";
    try {
      window.localStorage.setItem(LANG_KEY, language);
    } catch {
      // ignore
    }
  }, [language]);

  useEffect(() => {
    try {
      window.localStorage.setItem(VIEW_KEY, view);
    } catch {
      // ignore
    }
  }, [view]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const cfg = await refreshConfig();
      if (cancelled) return;
      // Only pull live data once the lock state is known (unlocked vs locked).
      if (cfg) {
        await Promise.allSettled([
          refreshBrief(language),
          refreshActions(),
          refreshAudit(),
          refreshInbox(),
          refreshDeadlines(),
          refreshNotifications(),
        ]);
      }
      if (cancelled) return;
      const params = new URLSearchParams(window.location.search);
      if (params.get("google") === "connected") {
        showToast(COPY[initialLanguage()].googleConnected, "good");
        await Promise.allSettled([
          refreshConfig(),
          refreshBrief(),
          refreshActions(),
          refreshInbox(),
          refreshDeadlines(),
          refreshNotifications(),
        ]);
      }
      if (params.has("google")) {
        params.delete("google");
        const query = params.toString();
        window.history.replaceState(
          {},
          "",
          `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
        );
      }
      setReady(true);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!ready) return undefined;
    const timer = window.setInterval(() => {
      refreshNotifications();
      if (document.visibilityState === "visible") {
        refreshInbox();
        refreshDeadlines();
      }
    }, 40000);
    return () => window.clearInterval(timer);
  }, [ready, refreshDeadlines, refreshInbox, refreshNotifications]);

  useEffect(() => {
    return () => {
      micRef.current?.stop();
      stopSpeech();
    };
  }, []);

  useEffect(() => {
    if (view === "inbox") refreshInbox();
    if (view === "deadlines") refreshDeadlines();
    if (view === "activity") refreshAudit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  const speak = useCallback(
    async (text, lang = language) => {
      if (!text) return;
      setPlaying(true);
      try {
        await speakText({ text, language: lang, useServerTTS: serverTts });
      } catch {
        showToast(t.voiceUnsupported, "bad");
      } finally {
        setPlaying(false);
      }
    },
    [language, serverTts, showToast, t.voiceUnsupported],
  );

  const togglePlay = useCallback(() => {
    if (playing) {
      stopSpeech();
      setPlaying(false);
      return;
    }
    if (brief?.text) speak(brief.text, language);
  }, [brief, language, playing, speak]);

  const send = useCallback(
    async (text, { voice = false, navigate = false } = {}) => {
      const trimmed = text.trim();
      if (!trimmed || thinking) return;
      const userMessage = {
        id: nextId("user"),
        role: "user",
        text: trimmed,
        language,
      };
      setMessages((prev) => [...prev, userMessage]);
      if (navigate) setView("chat");
      setThinking(true);
      try {
        const result = await api.post("/api/chat", { message: trimmed, language });
        mergeActions(result.cards || []);
        if (result.cards?.length) {
          setPending((prev) => {
            const seen = new Set(prev.map((action) => action.id));
            const fresh = result.cards.filter(
              (action) => action.status === "pending" && !seen.has(action.id),
            );
            return [...fresh, ...prev];
          });
        }
        const assistantMessage = {
          id: nextId("assistant"),
          role: "assistant",
          text: result.reply,
          language: result.language || language,
          cardIds: (result.cards || []).map((card) => card.id),
          sources: result.sources || [],
          flags: result.flags || [],
        };
        setMessages((prev) => [...prev, assistantMessage]);
        refreshAudit();
        refreshNotifications();
        // Spark always answers out loud (speech + text), even when the user
        // did not explicitly ask for a voice reply.
        speak(result.reply, result.language || language);
      } catch {
        setMessages((prev) => [
          ...prev,
          {
            id: nextId("assistant"),
            role: "assistant",
            text: t.error,
            error: true,
            language,
          },
        ]);
      } finally {
        setThinking(false);
      }
    },
    [language, mergeActions, refreshAudit, refreshNotifications, speak, t.error, thinking],
  );

  const handleScan = useCallback(async () => {
    if (scanning || thinking) return;
    setScanning(true);
    try {
      if (config?.capabilities?.mode === "live") {
        await api.post("/api/sync").catch(() => null);
        await Promise.allSettled([refreshDeadlines("active"), refreshInbox(), refreshNotifications()]);
      }
      const prompt =
        language === "hi" ? "मेरे ईमेल में डेडलाइन खोजो" : "Find deadlines in my emails";
      await send(prompt, { navigate: true });
    } finally {
      setScanning(false);
    }
  }, [
    config?.capabilities?.mode,
    language,
    refreshDeadlines,
    refreshInbox,
    refreshNotifications,
    scanning,
    send,
    thinking,
  ]);

  const handleAddDeadline = useCallback(
    async (deadline) => {
      const id = deadline.id || deadline.email_id;
      try {
        const result = await api.post(`/api/deadlines/${id}/add`, { language });
        mergeActions([result.action]);
        setPending((prev) =>
          prev.some((action) => action.id === result.action.id)
            ? prev
            : [result.action, ...prev],
        );
        showToast(result.reply, "good");
        setView("activity");
        refreshAudit();
      } catch {
        showToast(t.error, "bad");
      }
    },
    [language, mergeActions, refreshAudit, showToast, t.error],
  );

  const handleDeadlineAction = useCallback(
    async (id, action) => {
      setActionBusy((prev) => ({ ...prev, [id]: true }));
      try {
        await api.post(
          `/api/deadlines/${id}/${action}`,
          action === "snooze" ? { days: 1 } : undefined,
        );
        showToast(t.saved, "good");
        await Promise.allSettled([refreshDeadlines(), refreshBrief(), refreshNotifications()]);
      } catch {
        showToast(t.error, "bad");
      } finally {
        setActionBusy((prev) => {
          const next = { ...prev };
          delete next[id];
          return next;
        });
      }
    },
    [refreshBrief, refreshDeadlines, refreshNotifications, showToast, t.error, t.saved],
  );

  const decide = useCallback(
    async (actionId, decision) => {
      setActionBusy((prev) => ({ ...prev, [actionId]: true }));
      try {
        const result = await api.post(`/api/actions/${actionId}/${decision}`);
        mergeActions([result.action]);
        setPending(result.pending || []);
        refreshAudit();
        if (decision === "approve") {
          showToast(
            language === "hi" ? result.message_hi : result.message,
            "good",
            result.action.undoable ? result.action.id : null,
          );
        } else if (decision === "reject") {
          showToast(language === "hi" ? result.message_hi : result.message, "neutral");
        } else {
          showToast(language === "hi" ? result.message_hi : result.message, "good");
        }
      } catch (error) {
        showToast(t.error, "bad");
        if (error?.status === 409) refreshActions();
      } finally {
        setActionBusy((prev) => {
          const next = { ...prev };
          delete next[actionId];
          return next;
        });
      }
    },
    [language, mergeActions, refreshActions, refreshAudit, showToast, t.error],
  );

  const handleApprove = useCallback((id) => decide(id, "approve"), [decide]);
  const handleReject = useCallback((id) => decide(id, "reject"), [decide]);
  const handleUndo = useCallback(
    async (id) => {
      setToast(null);
      await decide(id, "undo");
    },
    [decide],
  );

  const handleMic = useCallback(() => {
    if (mic !== "idle") {
      micRef.current?.stop();
      micRef.current = null;
      setMic("idle");
      return;
    }
    stopSpeech();
    setPlaying(false);
    const session = startMic({
      mode: serverStt ? "server" : "browser",
      language,
      onText: (text) => {
        setMic("idle");
        send(text, { voice: true });
      },
      onState: (state) => setMic(state),
      onError: () => {
        setMic("idle");
        showToast(t.voiceUnsupported, "bad");
      },
    });
    micRef.current = session;
  }, [language, mic, send, serverStt, showToast, t.voiceUnsupported]);

  const handleLanguage = useCallback(
    (next) => {
      if (next === language) return;
      setLanguage(next);
      refreshBrief(next);
    },
    [language, refreshBrief],
  );

  const handleConnect = useCallback(async () => {
    try {
      const result = await api.get("/api/auth/google/start");
      if (result?.url) window.location.href = result.url;
    } catch {
      showToast(t.error, "bad");
    }
  }, [showToast, t.error]);

  const handleDisconnect = useCallback(async () => {
    try {
      await api.post("/api/auth/google/disconnect");
      await Promise.allSettled([
        refreshConfig(),
        refreshBrief(),
        refreshActions(),
        refreshInbox(),
        refreshDeadlines(),
      ]);
      showToast(language === "hi" ? "Google डिस्कनेक्ट हो गया।" : "Google disconnected.", "neutral");
    } catch {
      showToast(t.error, "bad");
    }
  }, [
    language,
    refreshActions,
    refreshBrief,
    refreshConfig,
    refreshDeadlines,
    refreshInbox,
    showToast,
    t.error,
  ]);

  const handleUnlock = useCallback(
    async (event) => {
      event.preventDefault();
      const password = unlock.trim();
      if (!password) return;
      setUnlocking(true);
      setUnlockError("");
      setOwnerToken(password);
      try {
        const payload = await api.get("/api/config");
        setConfig(payload);
        setLocked(false);
        setUnlock("");
        showToast(t.unlocked, "good");
        await Promise.allSettled([
          refreshBrief(language),
          refreshInbox(),
          refreshDeadlines(),
          refreshNotifications(),
        ]);
      } catch (error) {
        setOwnerToken("");
        const message = error?.status === 401 ? t.unlockWrong : t.error;
        setUnlockError(message);
        showToast(message, "bad");
      } finally {
        setUnlocking(false);
      }
    },
    [
      language,
      refreshBrief,
      refreshDeadlines,
      refreshInbox,
      refreshNotifications,
      showToast,
      t.error,
      t.unlockWrong,
      t.unlocked,
      unlock,
    ],
  );

  const handleRefresh = useCallback(async () => {
    await Promise.allSettled([
      refreshConfig(),
      refreshBrief(),
      refreshActions(),
      refreshAudit(),
      refreshInbox(),
      refreshDeadlines(),
      refreshNotifications(),
    ]);
  }, [
    refreshActions,
    refreshAudit,
    refreshBrief,
    refreshConfig,
    refreshDeadlines,
    refreshInbox,
    refreshNotifications,
  ]);

  const handleSettingsChanged = useCallback(async () => {
    await Promise.allSettled([
      refreshConfig(),
      refreshBrief(),
      refreshInbox(),
      refreshDeadlines(),
      refreshNotifications(),
    ]);
  }, [refreshBrief, refreshConfig, refreshDeadlines, refreshInbox, refreshNotifications]);

  const handleMarkMessageRead = useCallback(async (id) => {
    try {
      const result = await api.post(`/api/messages/${id}/read`);
      setInbox((prev) =>
        prev.map((message) =>
          message.id === id ? { ...message, unread: false } : message,
        ),
      );
      if (result.stats) setInboxStats(result.stats);
    } catch {
      // leave the unread dot in place if the call failed
    }
  }, []);

  const handleMarkNotificationRead = useCallback(async (id) => {
    try {
      const result = await api.post(`/api/notifications/${id}/read`);
      setNotifications((prev) =>
        prev.map((item) => (item.id === id ? { ...item, read: true } : item)),
      );
      setUnread(result.unread ?? 0);
      lastUnreadRef.current = result.unread ?? 0;
    } catch {
      // ignore
    }
  }, []);

  const handleReadAll = useCallback(async () => {
    try {
      await api.post("/api/notifications/read-all");
      setNotifications((prev) => prev.map((item) => ({ ...item, read: true })));
      setUnread(0);
      lastUnreadRef.current = 0;
    } catch {
      // ignore
    }
  }, []);

  const handleOpenNotification = useCallback(
    (item) => {
      setNotifOpen(false);
      if (!item.read) handleMarkNotificationRead(item.id);
      if (item.kind === "deadline" || item.meta?.deadline_id) {
        setView("deadlines");
        refreshDeadlines("active");
      } else if (item.source === "whatsapp" || item.source === "gmail" || item.kind === "message") {
        setView("inbox");
        refreshInbox();
      }
    },
    [handleMarkNotificationRead, refreshDeadlines, refreshInbox],
  );

  const enableNotifications = useCallback(async () => {
    if (typeof Notification === "undefined") {
      showToast(t.voiceUnsupported, "bad");
      return;
    }
    try {
      const permission = await Notification.requestPermission();
      setNotificationPermission(permission);
      if (permission === "granted") showToast(t.notificationsOn, "good");
      else if (permission === "denied") showToast(t.notificationsBlocked, "bad");
    } catch {
      showToast(t.notificationsBlocked, "bad");
    }
  }, [showToast, t.notificationsBlocked, t.notificationsOn, t.voiceUnsupported]);

  const handleNavigate = useCallback(
    (next) => {
      setView(next);
      if (next === "activity") refreshAudit();
      if (next === "inbox") refreshInbox();
      if (next === "deadlines") refreshDeadlines();
      if (next === "settings") refreshConfig();
    },
    [refreshAudit, refreshConfig, refreshDeadlines, refreshInbox],
  );

  const handleAsk = useCallback(
    (text) => {
      setView("chat");
      send(text);
    },
    [send],
  );

  const pendingCount = pending.length;
  const mode = config?.capabilities?.mode || "demo";
  const profileName = config?.profile?.name || "there";
  const suggestions = useMemo(() => config?.prompts || t.suggestions, [config, t.suggestions]);

  // Full-screen black gate: nothing but the password prompt is visible until
  // the owner unlocks Spark.
  if (locked) {
    return (
      <div className="lock-screen">
        <div className="lock-screen-card">
          <span className="lock-screen-mark">
            <SparkIcon size={30} />
          </span>
          <strong className="lock-screen-title">{t.unlockTitle}</strong>
          <p className="lock-screen-sub">{t.unlockSub}</p>
          <form className="lock-form" onSubmit={handleUnlock}>
            <input
              type="password"
              value={unlock}
              onChange={(event) => setUnlock(event.target.value)}
              placeholder={t.ownerTokenPlaceholder}
              aria-label={t.accessPassword}
              autoComplete="current-password"
            />
            <button type="submit" className="btn primary" disabled={unlocking || !unlock.trim()}>
              {unlocking ? t.unlocking : t.unlock}
            </button>
          </form>
          {unlockError && <p className="lock-error">{unlockError}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <Sidebar
        t={t}
        language={language}
        onLanguage={handleLanguage}
        view={view}
        onNavigate={handleNavigate}
        pendingCount={pendingCount}
        config={config}
        onConnect={handleConnect}
        onDisconnect={handleDisconnect}
        unread={unread}
        onNotifications={() => setNotifOpen(true)}
      />

      <div className="main-column">
        <header className="mobile-topbar">
          <button type="button" className="mobile-brand" onClick={() => handleNavigate("today")}>
            <SparkIcon size={22} />
            <span>Spark</span>
          </button>
          <div className="mobile-topbar-actions">
            <button
              type="button"
              className="icon-btn notif-mobile"
              onClick={() => setNotifOpen(true)}
              aria-label={t.notifications}
            >
              <BellIcon size={18} />
              {unread > 0 && <span className="nav-badge small">{unread}</span>}
            </button>
            <span className={`mode-chip tiny ${mode}`}>
              <span className="dot" />
              {mode === "live" ? t.liveMode : t.demoMode}
            </span>
            <button
              type="button"
              className="icon-btn lang-icon"
              onClick={() => handleNavigate("settings")}
              aria-label={t.navSettings}
              title={t.navSettings}
            >
              <SettingsIcon size={17} />
            </button>
            <button
              type="button"
              className="icon-btn lang-icon"
              onClick={() => handleLanguage(language === "en" ? "hi" : "en")}
              aria-label="Switch language"
              title="Switch language"
            >
              <GlobeIcon size={17} />
              <span>{language === "en" ? "EN" : "हिं"}</span>
            </button>
          </div>
        </header>

        <main className="main">
          {locked && (
            <div className="flag-banner lock-banner">
              <span className="flag-icon">
                <ShieldIcon size={17} />
              </span>
              <div className="lock-copy">
                <strong>{t.unlockTitle}</strong>
                <p>{t.unlockSub}</p>
                <form className="lock-form" onSubmit={handleUnlock}>
                  <input
                    type="password"
                    value={unlock}
                    onChange={(event) => setUnlock(event.target.value)}
                    placeholder={t.ownerTokenPlaceholder}
                    aria-label={t.accessPassword}
                    autoComplete="current-password"
                  />
                  <button
                    type="submit"
                    className="btn primary"
                    disabled={unlocking || !unlock.trim()}
                  >
                    {unlocking ? t.unlocking : t.unlock}
                  </button>
                </form>
                {unlockError && <p className="lock-error">{unlockError}</p>}
              </div>
            </div>
          )}
          {view === "today" && (
            <TodayView
              t={t}
              language={language}
              brief={brief}
              briefLoading={briefLoading}
              config={config}
              pendingActions={pending}
              playing={playing}
              scanning={scanning || thinking}
              onPlay={togglePlay}
              onRefresh={handleRefresh}
              onScan={handleScan}
              onAddDeadline={handleAddDeadline}
              onNavigate={handleNavigate}
            />
          )}
          {view === "chat" && (
            <ChatView
              t={t}
              language={language}
              config={{ ...config, prompts: suggestions }}
              messages={messages}
              actionMap={actionsMap}
              actionBusy={actionBusy}
              thinking={thinking}
              mic={mic}
              onSend={send}
              onMic={handleMic}
              onApprove={handleApprove}
              onReject={handleReject}
              onUndo={handleUndo}
              onSpeak={speak}
            />
          )}
          {view === "inbox" && (
            <InboxView
              t={t}
              language={language}
              messages={inbox}
              stats={inboxStats}
              loading={inboxLoading}
              onRefresh={handleRefresh}
              onMarkRead={handleMarkMessageRead}
              onAsk={handleAsk}
            />
          )}
          {view === "deadlines" && (
            <DeadlinesView
              t={t}
              language={language}
              deadlines={deadlines}
              loading={deadlinesLoading}
              status={deadlineStatus}
              onStatus={(status) => {
                setDeadlineStatus(status);
                refreshDeadlines(status);
              }}
              onRefresh={() => refreshDeadlines()}
              onAdd={handleAddDeadline}
              onComplete={(id) => handleDeadlineAction(id, "complete")}
              onDismiss={(id) => handleDeadlineAction(id, "dismiss")}
              onSnooze={(id) => handleDeadlineAction(id, "snooze")}
              actionBusy={actionBusy}
            />
          )}
          {view === "activity" && (
            <ActivityView
              t={t}
              language={language}
              pendingActions={pending}
              actionMap={actionsMap}
              audit={audit}
              loading={auditLoading}
              actionBusy={actionBusy}
              onApprove={handleApprove}
              onReject={handleReject}
              onUndo={handleUndo}
              onRefresh={handleRefresh}
            />
          )}
          {view === "settings" && (
            <SettingsView
              t={t}
              language={language}
              config={config}
              showToast={showToast}
              onChanged={handleSettingsChanged}
              onConnect={handleConnect}
              onDisconnect={handleDisconnect}
              onEnableNotifications={enableNotifications}
              notificationPermission={notificationPermission}
            />
          )}
        </main>
      </div>

      <BottomNav
        t={t}
        view={view}
        onNavigate={handleNavigate}
        pendingCount={pendingCount}
        unread={unread}
      />
      <NotificationsPanel
        t={t}
        language={language}
        notifications={notifications}
        unread={unread}
        open={notifOpen}
        onClose={() => setNotifOpen(false)}
        onRead={handleMarkNotificationRead}
        onReadAll={handleReadAll}
        onOpenNotification={handleOpenNotification}
      />
      <Toast toast={toast} onClose={closeToast} onUndo={handleUndo} language={language} />

      {!ready && (
        <div className="splash" role="status" aria-live="polite">
          <span className="splash-mark">
            <SparkIcon size={52} />
          </span>
          <span className="splash-name">Spark</span>
          <span className="splash-line">{COPY[language].tagline}</span>
          <span className="splash-loader">
            <span />
          </span>
          <span className="splash-foot">
            {profileName} · {COPY[language].footerNote}
          </span>
        </div>
      )}
    </div>
  );
}
