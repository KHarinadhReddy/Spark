import {
  ActivityIcon,
  BellIcon,
  CheckIcon,
  ClockIcon,
  MicIcon,
  SparkIcon,
  SunIcon,
  ExternalIcon,
  CalendarIcon,
  MailIcon,
  InboxIcon,
  SettingsIcon,
  ShieldIcon,
} from "../icons";

const NAV = [
  { id: "today", icon: SunIcon, key: "navToday" },
  { id: "chat", icon: MicIcon, key: "navChat" },
  { id: "inbox", icon: InboxIcon, key: "navInbox" },
  { id: "deadlines", icon: ClockIcon, key: "navDeadlines" },
  { id: "activity", icon: ActivityIcon, key: "navActivity" },
  { id: "settings", icon: SettingsIcon, key: "navSettings" },
];

const MOBILE_NAV = ["today", "chat", "inbox", "deadlines", "activity"];

const CAPABILITIES = [
  { key: "calendar", icon: CalendarIcon },
  { key: "gmail", icon: MailIcon },
  { key: "drive", icon: ShieldIcon },
];

function llmLabel(llm, t) {
  if (llm === "gemini") return "Gemini Flash";
  if (llm === "groq") return "Groq Llama";
  if (llm === "bedrock" || llm === "bedrock-claude") return t.bedrock;
  return t.localPlanner;
}

function voiceLabel(voice, t) {
  if (voice === "elevenlabs") return t.elevenlabs;
  if (voice === "edge-tts") return "Edge neural";
  return t.browserVoice;
}

export function Sidebar({
  t,
  language,
  onLanguage,
  view,
  onNavigate,
  pendingCount,
  config,
  onConnect,
  onDisconnect,
  unread,
  onNotifications,
}) {
  const mode = config?.capabilities?.mode || "demo";
  const llm = config?.capabilities?.llm || "local-planner";
  const voice = config?.capabilities?.voice || "browser";

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">
          <SparkIcon size={30} />
        </span>
        <div>
          <span className="brand-name">Spark</span>
          <span className="brand-tagline">{t.tagline}</span>
        </div>
      </div>

      <nav className="side-nav" aria-label="Main">
        {NAV.map((item) => {
          const Icon = item.icon;
          return (
            <button
              type="button"
              key={item.id}
              className={`nav-item ${view === item.id ? "active" : ""}`}
              onClick={() => onNavigate(item.id)}
            >
              <Icon size={18} />
              <span>{t[item.key]}</span>
              {item.id === "activity" && pendingCount > 0 && (
                <span className="nav-badge">{pendingCount}</span>
              )}
              {item.id === "inbox" && unread > 0 && (
                <span className="nav-badge soft">{unread}</span>
              )}
            </button>
          );
        })}
      </nav>

      <button type="button" className="nav-item notif-nav" onClick={onNotifications}>
        <BellIcon size={18} />
        <span>{t.notifications}</span>
        {unread > 0 && <span className="nav-badge soft">{unread}</span>}
      </button>

      <div className="side-section">
        <span className="side-label">{t.workspace}</span>
        <div className={`mode-card ${mode}`}>
          <div className="mode-line">
            <span className="dot" />
            <strong>{mode === "live" ? t.liveMode : t.demoMode}</strong>
          </div>
          <p>{mode === "live" ? t.liveHint : t.demoHint}</p>
          {config?.google?.configured && (
            <button
              type="button"
              className="mode-action"
              onClick={mode === "live" ? onDisconnect : onConnect}
            >
              {mode === "live" ? t.disconnect : t.connectGoogle}
            </button>
          )}
          <div className="capability-row">
            {CAPABILITIES.map(({ key, icon: Icon }) => (
              <span key={key} className="capability-pill" title={`${key}: ${config?.capabilities?.[key] || "demo"}`}>
                <Icon size={13} />
                {key === "gmail" ? "Mail" : key === "calendar" ? "Cal" : "Drive"}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="side-meta">
        <div>
          <span className="side-label">{t.llm}</span>
          <span className="meta-value">
            <CheckIcon size={13} />
            {llmLabel(llm, t)}
          </span>
        </div>
        <div>
          <span className="side-label">{t.voice}</span>
          <span className="meta-value">
            <CheckIcon size={13} />
            {voiceLabel(voice, t)}
          </span>
        </div>
      </div>

      <div className="side-footer">
        <div className="lang-toggle" role="group" aria-label="Language">
          <button
            type="button"
            className={language === "en" ? "active" : ""}
            onClick={() => onLanguage("en")}
          >
            EN
          </button>
          <button
            type="button"
            className={language === "hi" ? "active" : ""}
            onClick={() => onLanguage("hi")}
          >
            हिं
          </button>
        </div>
        <p className="powered">
          <ShieldIcon size={13} />
          {t.powered}
        </p>
        <a
          className="github-link"
          href="https://github.com/KHarinadhReddy/Spark"
          target="_blank"
          rel="noreferrer"
        >
          <ExternalIcon size={13} />
          github.com/KHarinadhReddy/Spark
        </a>
        <p className="footer-note">{t.footerNote}</p>
      </div>
    </aside>
  );
}

export function BottomNav({ t, view, onNavigate, pendingCount, unread }) {
  const items = NAV.filter((item) => MOBILE_NAV.includes(item.id));
  return (
    <nav className="bottom-nav" aria-label="Main">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <button
            type="button"
            key={item.id}
            className={`bottom-nav-item ${view === item.id ? "active" : ""}`}
            onClick={() => onNavigate(item.id)}
          >
            <span className="bottom-icon">
              <Icon size={20} />
              {item.id === "activity" && pendingCount > 0 && (
                <span className="nav-badge small">{pendingCount}</span>
              )}
              {item.id === "inbox" && unread > 0 && (
                <span className="nav-badge small soft">{unread}</span>
              )}
            </span>
            <span>{t[item.key]}</span>
          </button>
        );
      })}
    </nav>
  );
}
