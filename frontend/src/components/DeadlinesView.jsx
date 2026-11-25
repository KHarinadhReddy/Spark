import { useMemo } from "react";
import {
  AlertIcon,
  CalendarIcon,
  CheckIcon,
  ClockIcon,
  RefreshIcon,
  XIcon,
} from "../icons";

function dateParts(value) {
  if (!value) return { day: "—", month: "", weekday: "" };
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return { day: "—", month: "", weekday: "" };
  return {
    day: String(date.getDate()).padStart(2, "0"),
    month: new Intl.DateTimeFormat("en-IN", { month: "short" }).format(date),
    weekday: new Intl.DateTimeFormat("en-IN", { weekday: "short" }).format(date),
  };
}

function dayDiff(value) {
  if (!value) return null;
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((date - today) / 86400000);
}

function relativeDue(value, language) {
  const diff = dayDiff(value);
  if (diff === null) return language === "hi" ? "तारीख नहीं" : "No date";
  if (diff < 0) return language === "hi" ? `${Math.abs(diff)} दिन पहले` : `${Math.abs(diff)}d overdue`;
  if (diff === 0) return language === "hi" ? "आज" : "Today";
  if (diff === 1) return language === "hi" ? "कल" : "Tomorrow";
  return language === "hi" ? `${diff} दिन में` : `in ${diff} days`;
}

export function DeadlinesView({
  t,
  language,
  deadlines,
  loading,
  status,
  onStatus,
  onRefresh,
  onAdd,
  onComplete,
  onDismiss,
  onSnooze,
  actionBusy,
}) {
  const sorted = useMemo(
    () =>
      [...deadlines].sort((a, b) =>
        (a.due_date || a.date || "").localeCompare(b.due_date || b.date || ""),
      ),
    [deadlines],
  );

  const filters = [
    ["active", t.filterActive],
    ["completed", t.filterCompleted],
    ["all", t.filterAllDeadlines],
  ];

  return (
    <div className="page deadlines-page">
      <header className="page-head">
        <div>
          <p className="eyebrow">{language === "hi" ? "डेडलाइन रडार" : "Deadline radar"}</p>
          <h1>{t.deadlinesTitle}</h1>
          <p>{t.deadlinesSub}</p>
        </div>
        <div className="head-action-row">
          <div className="segmented">
            {filters.map(([id, label]) => (
              <button
                type="button"
                key={id}
                className={status === id ? "active" : ""}
                onClick={() => onStatus(id)}
              >
                {label}
              </button>
            ))}
          </div>
          <button type="button" className="btn ghost" onClick={onRefresh} disabled={loading}>
            <RefreshIcon size={16} />
            {t.refresh}
          </button>
        </div>
      </header>

      {sorted.length === 0 ? (
        <section className="panel">
          <div className="empty-state with-icon">
            <ClockIcon size={24} />
            <p>{t.noDeadlineMatch}</p>
            <button type="button" className="btn subtle" onClick={onRefresh}>
              {t.refresh}
            </button>
          </div>
        </section>
      ) : (
        <div className="deadline-cards">
          {sorted.map((deadline) => {
            const id = deadline.id || deadline.email_id;
            const due = deadline.due_date || deadline.date;
            const parts = dateParts(due);
            const diff = dayDiff(due);
            const busy = Boolean(actionBusy?.[id]);
            const isDone = deadline.status === "completed";
            return (
              <article
                key={id}
                className={`deadline-card priority-${deadline.priority || "normal"} ${
                  diff !== null && diff < 0 && !isDone ? "overdue" : ""
                } ${isDone ? "completed" : ""}`}
              >
                <div className="date-chip large">
                  <span>{parts.day}</span>
                  <em>{parts.month}</em>
                </div>
                <div className="deadline-card-main">
                  <div className="deadline-card-top">
                    <h2>{deadline.title || deadline.subject}</h2>
                    <span className={`tag ${diff !== null && diff <= 2 ? "bad" : diff !== null && diff <= 7 ? "warn" : ""}`}>
                      <ClockIcon size={11} />
                      {relativeDue(due, language)}
                    </span>
                  </div>
                  <p>{deadline.evidence || deadline.snippet || ""}</p>
                  <div className="deadline-card-meta">
                    <span className={`tag source-${deadline.source || "gmail"}`}>
                      {deadline.source || "gmail"}
                    </span>
                    {deadline.category && <span className="tag">{deadline.category}</span>}
                    {deadline.priority && (
                      <span className={`tag ${deadline.priority === "urgent" ? "bad" : deadline.priority === "high" ? "warn" : ""}`}>
                        {deadline.priority}
                      </span>
                    )}
                    {deadline.confidence != null && (
                      <span className="deadline-confidence">
                        {t.confidence} {Math.round(Number(deadline.confidence) * 100)}%
                      </span>
                    )}
                    {deadline.due_at && (
                      <span className="tag">
                        <ClockIcon size={11} />
                        {deadline.due_at.slice(11, 16)}
                      </span>
                    )}
                    {isDone && (
                      <span className="tag good">
                        <CheckIcon size={11} />
                        {t.filterCompleted}
                      </span>
                    )}
                  </div>
                </div>
                <div className="deadline-card-actions">
                  {!isDone && (
                    <>
                      <button
                        type="button"
                        className="btn primary"
                        onClick={() => onAdd(deadline)}
                        disabled={busy}
                      >
                        <CalendarIcon size={15} />
                        {t.addToCalendar}
                      </button>
                      <button
                        type="button"
                        className="mini-btn good"
                        onClick={() => onComplete(id)}
                        disabled={busy}
                      >
                        <CheckIcon size={13} />
                        {t.complete}
                      </button>
                      <button
                        type="button"
                        className="mini-btn"
                        onClick={() => onSnooze(id)}
                        disabled={busy}
                      >
                        <ClockIcon size={13} />
                        {t.snooze}
                      </button>
                      <button
                        type="button"
                        className="mini-btn bad"
                        onClick={() => onDismiss(id)}
                        disabled={busy}
                      >
                        <XIcon size={13} />
                        {t.dismiss}
                      </button>
                    </>
                  )}
                  {isDone && (
                    <span className="done-note">
                      <CheckIcon size={14} />
                      {t.filterCompleted}
                    </span>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}

      <footer className="page-footer">
        <span>
          <AlertIcon size={14} />
          {language === "hi"
            ? "डेडलाइन असली संदेशों से बनती हैं; कैलेंडर में जोड़ना आपकी मंज़ूरी से होता है।"
            : "Deadlines come from real messages; adding one to Calendar always needs your approval."}
        </span>
        <span className="footer-dot">·</span>
        <span>{t.footerNote}</span>
      </footer>
    </div>
  );
}
