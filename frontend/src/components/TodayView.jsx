import { useMemo } from "react";
import {
  ArrowRightIcon,
  CalendarIcon,
  CheckIcon,
  ClockIcon,
  MailIcon,
  PlayIcon,
  PlusIcon,
  RefreshIcon,
  SearchIcon,
  ShieldIcon,
  StopIcon,
  UndoIcon,
  ActivityIcon,
  AlertIcon,
} from "../icons";

function locale(language) {
  return language === "hi" ? "hi-IN" : "en-IN";
}

function relativeDays(iso, language) {
  const target = new Date(`${iso}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.round((target - today) / 86400000);
  if (diff <= 0) return language === "hi" ? "आज" : "Today";
  if (diff === 1) return language === "hi" ? "कल" : "Tomorrow";
  return language === "hi" ? `${diff} दिन` : `in ${diff} days`;
}

function timeLabel(iso, language) {
  try {
    return new Intl.DateTimeFormat(locale(language), {
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date(iso));
  } catch {
    return "";
  }
}

export function TodayView({
  t,
  language,
  brief,
  briefLoading,
  config,
  pendingActions,
  playing,
  scanning,
  onPlay,
  onRefresh,
  onScan,
  onAddDeadline,
  onNavigate,
}) {
  const now = new Date();
  const greeting =
    now.getHours() < 12 ? t.greetingMorning : now.getHours() < 17 ? t.greetingAfternoon : t.greetingEvening;
  const name = config?.profile?.name?.split(" ")[0] || "Harinadh";
  const dateLabel = new Intl.DateTimeFormat(locale(language), {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(now);
  const events = brief?.events || [];
  const deadlines = brief?.deadlines || [];
  const flagCount = brief?.flags?.length || 0;
  const mode = config?.capabilities?.mode || "demo";

  const cardSources = useMemo(
    () =>
      new Set(
        pendingActions.filter((action) => action.status === "pending").map((action) => action.source),
      ),
    [pendingActions],
  );

  return (
    <div className="page today-page">
      <header className="hero">
        <div className="hero-top">
          <p className="eyebrow">
            {dateLabel} · {t.todayEyebrow}
          </p>
          <button type="button" className="icon-btn" onClick={onRefresh} aria-label={t.refresh} title={t.refresh}>
            <RefreshIcon size={17} />
          </button>
        </div>
        <h1>
          {greeting}, <span className="accent">{name}</span>.
        </h1>
        <p className="hero-brief">
          {briefLoading && !brief ? t.briefLoading : brief?.text || t.heroSub}
        </p>
        <div className="hero-actions">
          <button type="button" className="btn primary big" onClick={onPlay} disabled={!brief}>
            {playing ? <StopIcon size={16} /> : <PlayIcon size={16} />}
            {playing ? t.stopBrief : t.playBrief}
          </button>
          <button type="button" className="btn ghost big" onClick={onScan} disabled={scanning}>
            <SearchIcon size={16} />
            {scanning ? t.scanning : t.scanInbox}
          </button>
          <span className={`mode-chip ${mode}`}>
            <span className="dot" />
            {mode === "live" ? t.liveMode : t.demoMode}
          </span>
        </div>
      </header>

      {flagCount > 0 && (
        <div className="flag-banner compact" role="note">
          <span className="flag-icon">
            <AlertIcon size={18} />
          </span>
          <div>
            <strong>{t.flagTitle}</strong>
            <p>{flagCount === 1 ? t.flagOne : t.flagMany.replace("{n}", flagCount)}</p>
          </div>
        </div>
      )}

      <section className="stat-grid" aria-label="Overview">
        <div className="stat-card">
          <span className="stat-icon">
            <CalendarIcon size={18} />
          </span>
          <span className="stat-value">{events.length}</span>
          <span className="stat-label">{t.statClasses}</span>
          <span className="stat-foot">{t.schedule}</span>
        </div>
        <div className="stat-card">
          <span className="stat-icon">
            <ClockIcon size={18} />
          </span>
          <span className="stat-value">{deadlines.length}</span>
          <span className="stat-label">{t.statDeadlines}</span>
          <span className="stat-foot">{t.radar}</span>
        </div>
        <button type="button" className="stat-card clickable" onClick={() => onNavigate("activity")}>
          <span className="stat-icon">
            <ShieldIcon size={18} />
          </span>
          <span className="stat-value">{pendingActions.length}</span>
          <span className="stat-label">{t.statPending}</span>
          <span className="stat-foot link">
            {t.seeInChat} <ArrowRightIcon size={13} />
          </span>
        </button>
      </section>

      <div className="today-grid">
        <section className="panel" aria-labelledby="schedule-title">
          <header className="panel-head">
            <div>
              <p className="eyebrow">{t.scheduleCount}</p>
              <h2 id="schedule-title">{t.schedule}</h2>
            </div>
            <span className="count-pill">{events.length}</span>
          </header>
          {briefLoading && events.length === 0 ? (
            <div className="skeleton-list">
              <span className="skeleton" />
              <span className="skeleton" />
              <span className="skeleton" />
            </div>
          ) : events.length === 0 ? (
            <p className="empty-state">{t.noEvents}</p>
          ) : (
            <ol className="agenda">
              {events.map((event) => (
                <li key={event.id} className="agenda-item">
                  <span className="agenda-time">{timeLabel(event.start, language)}</span>
                  <span className="agenda-line" />
                  <div className="agenda-body">
                    <strong>{event.summary}</strong>
                    <span>{event.location || event.description || "—"}</span>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </section>

        <section className="panel radar-panel" aria-labelledby="radar-title">
          <header className="panel-head">
            <div>
              <p className="eyebrow">{t.radarCount}</p>
              <h2 id="radar-title">{t.radar}</h2>
            </div>
            <span className="count-pill">{deadlines.length}</span>
          </header>
          {briefLoading && deadlines.length === 0 ? (
            <div className="skeleton-list">
              <span className="skeleton" />
              <span className="skeleton" />
              <span className="skeleton" />
            </div>
          ) : deadlines.length === 0 ? (
            <p className="empty-state">{t.noDeadlines}</p>
          ) : (
            <ul className="deadline-list">
              {deadlines.map((deadline) => {
                const date = new Date(`${deadline.date}T00:00:00`);
                const ready = cardSources.has(`email:${deadline.email_id}`);
                return (
                  <li key={deadline.email_id} className={`deadline-row ${ready ? "ready" : ""}`}>
                    <span className="date-chip">
                      <b>{String(date.getDate()).padStart(2, "0")}</b>
                      <span>
                        {new Intl.DateTimeFormat(locale(language), { month: "short" }).format(date)}
                      </span>
                    </span>
                    <span className="deadline-main">
                      <strong>{deadline.subject}</strong>
                      <span className="deadline-meta">
                        {deadline.sender} · <em>{relativeDays(deadline.date, language)}</em>
                      </span>
                    </span>
                    {ready ? (
                      <button
                        type="button"
                        className="mini-btn ready"
                        onClick={() => onNavigate("activity")}
                      >
                        <CheckIcon size={13} />
                        {t.cardReady}
                      </button>
                    ) : (
                      <button type="button" className="mini-btn" onClick={() => onAddDeadline(deadline)}>
                        <PlusIcon size={13} />
                        {t.addToCalendar}
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>

      <section className="guardrail-strip" aria-label="Safety">
        <div>
          <span className="guard-icon">
            <MailIcon size={17} />
          </span>
          <strong>{t.guardReadTitle}</strong>
          <span>{t.guardReadBody}</span>
        </div>
        <div>
          <span className="guard-icon">
            <ShieldIcon size={17} />
          </span>
          <strong>{t.guardWriteTitle}</strong>
          <span>{t.guardWriteBody}</span>
        </div>
        <div>
          <span className="guard-icon">
            <UndoIcon size={17} />
          </span>
          <strong>{t.guardUndoTitle}</strong>
          <span>{t.guardUndoBody}</span>
        </div>
      </section>

      <footer className="page-footer">
        <span>
          <ActivityIcon size={14} />
          {t.demoStrip}
        </span>
        <span className="footer-dot">·</span>
        <span>{t.footerNote}</span>
      </footer>
    </div>
  );
}
