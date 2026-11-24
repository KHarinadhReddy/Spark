import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { COPY } from "./i18n";
import { speakText, startMic, stopSpeech } from "./voice";
import { Sidebar, BottomNav } from "./components/Sidebar";
import { TodayView } from "./components/TodayView";
import { ChatView } from "./components/ChatView";
import { ActivityView } from "./components/ActivityView";
import { Toast } from "./components/Toast";
import { SparkIcon, GlobeIcon } from "./icons";

const LANG_KEY = "spark.language";
const VIEW_KEY = "spark.view";

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
    if (["today", "chat", "activity"].includes(stored)) return stored;
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

  const micRef = useRef(null);
  const t = COPY[language];
  const voiceMode = config?.capabilities?.voice === "elevenlabs" ? "elevenlabs" : "browser";

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
      await Promise.allSettled([
        refreshConfig(),
        refreshBrief(language),
        refreshActions(),
        refreshAudit(),
      ]);
      if (cancelled) return;
      const params = new URLSearchParams(window.location.search);
      if (params.get("google") === "connected") {
        showToast(COPY[initialLanguage()].googleConnected, "good");
        await Promise.allSettled([refreshConfig(), refreshBrief(), refreshActions()]);
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
    return () => {
      micRef.current?.stop();
      stopSpeech();
    };
  }, []);

  const speak = useCallback(
    async (text, lang = language) => {
      if (!text) return;
      setPlaying(true);
      try {
        await speakText({ text, language: lang, useElevenLabs: voiceMode === "elevenlabs" });
      } catch {
        showToast(t.voiceUnsupported, "bad");
      } finally {
        setPlaying(false);
      }
    },
    [language, showToast, t.voiceUnsupported, voiceMode],
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
        if (voice) speak(result.reply, result.language || language);
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
    [language, mergeActions, refreshAudit, speak, t.error, thinking],
  );

  const handleScan = useCallback(async () => {
    if (scanning || thinking) return;
    setScanning(true);
    try {
      const prompt =
        language === "hi" ? "मेरे ईमेल में डेडलाइन खोजो" : "Find deadlines in my emails";
      await send(prompt, { navigate: true });
    } finally {
      setScanning(false);
    }
  }, [language, scanning, send, thinking]);

  const handleAddDeadline = useCallback(
    async (deadline) => {
      try {
        const result = await api.post(`/api/deadlines/${deadline.email_id}/add`, { language });
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
      mode: voiceMode,
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
  }, [language, mic, send, showToast, t.voiceUnsupported, voiceMode]);

  const handleLanguage = useCallback(
    (next) => {
      if (next === language) return;
      setLanguage(next);
      refreshBrief(next);
    },
    [language, refreshBrief],
  );

  const handleConnect = useCallback(() => {
    window.location.href = "/api/auth/google/start";
  }, []);

  const handleDisconnect = useCallback(async () => {
    try {
      await api.post("/api/auth/google/disconnect");
      await Promise.allSettled([refreshConfig(), refreshBrief(), refreshActions()]);
      showToast(language === "hi" ? "Google डिस्कनेक्ट हो गया।" : "Google disconnected.", "neutral");
    } catch {
      showToast(t.error, "bad");
    }
  }, [language, refreshActions, refreshBrief, refreshConfig, showToast, t.error]);

  const handleRefresh = useCallback(async () => {
    await Promise.allSettled([refreshConfig(), refreshBrief(), refreshActions(), refreshAudit()]);
  }, [refreshActions, refreshAudit, refreshBrief, refreshConfig]);

  const handleNavigate = useCallback((next) => {
    setView(next);
    if (next === "activity") refreshAudit();
  }, [refreshAudit]);

  const pendingCount = pending.length;
  const mode = config?.capabilities?.mode || "demo";
  const profileName = config?.profile?.name || "Harinadh";
  const suggestions = useMemo(() => config?.prompts || t.suggestions, [config, t.suggestions]);

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
      />

      <div className="main-column">
        <header className="mobile-topbar">
          <button type="button" className="mobile-brand" onClick={() => handleNavigate("today")}>
            <SparkIcon size={22} />
            <span>Spark</span>
          </button>
          <div className="mobile-topbar-actions">
            <span className={`mode-chip tiny ${mode}`}>
              <span className="dot" />
              {mode === "live" ? t.liveMode : t.demoMode}
            </span>
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
        </main>
      </div>

      <BottomNav t={t} view={view} onNavigate={handleNavigate} pendingCount={pendingCount} />
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
