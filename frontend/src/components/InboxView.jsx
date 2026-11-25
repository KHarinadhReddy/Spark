import { useMemo, useState } from "react";
import { api } from "../api";
import {
  ArrowRightIcon,
  CheckIcon,
  ClockIcon,
  InboxIcon,
  MailIcon,
  RefreshIcon,
  SearchIcon,
  SparkIcon,
  WhatsAppIcon,
  XIcon,
  AlertIcon,
} from "../icons";

function initials(value) {
  const clean = (value || "?").trim();
  const parts = clean.split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0]?.toUpperCase()).join("") || "?";
}

function sourceLabel(t, source) {
  if (source === "whatsapp") return t.sourceWhatsApp;
  if (source === "notification") return t.sourceNotification;
  return t.sourceGmail;
}

function SourceIcon({ source, size = 14 }) {
  if (source === "whatsapp") return <WhatsAppIcon size={size} />;
  if (source === "notification") return <InboxIcon size={size} />;
  return <MailIcon size={size} />;
}

function relativeTime(iso, language) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 10);
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const then = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diff = Math.round((start - then) / 86400000);
  if (diff === 0) {
    return new Intl.DateTimeFormat(language === "hi" ? "hi-IN" : "en-IN", {
      hour: "numeric",
      minute: "2-digit",
    }).format(date);
  }
  if (diff === 1) return language === "hi" ? "कल" : "Yesterday";
  if (diff > 1 && diff < 7) return language === "hi" ? `${diff} दिन पहले` : `${diff}d ago`;
  return new Intl.DateTimeFormat(language === "hi" ? "hi-IN" : "en-IN", {
    day: "2-digit",
    month: "short",
  }).format(date);
}

export function InboxView({
  t,
  language,
  messages,
  stats,
  loading,
  onRefresh,
  onMarkRead,
  onAsk,
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return messages.filter((message) => {
      if (filter === "unread" && !message.unread) return false;
      if (filter === "action" && !message.needs_action) return false;
      if (filter === "whatsapp" && message.source !== "whatsapp") return false;
      if (filter === "gmail" && message.source !== "gmail") return false;
      if (!needle) return true;
      return [message.subject, message.snippet, message.sender, message.sender_name]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [messages, filter, query]);

  async function openMessage(message) {
    setDetail({ ...message, body: message.snippet });
    setDetailLoading(true);
    try {
      const full = await api.get(`/api/messages/${message.id}?mark_read=true`);
      setDetail(full);
      if (message.unread) onMarkRead(message.id, true);
    } catch {
      // keep the snippet if the detail call fails
    } finally {
      setDetailLoading(false);
    }
  }

  const filters = [
    ["all", t.filterAll],
    ["unread", t.filterUnread],
    ["action", t.needsAction],
    ["gmail", "Gmail"],
    ["whatsapp", "WhatsApp"],
  ];

  return (
    <div className="page inbox-page">
      <header className="page-head">
        <div>
          <p className="eyebrow">{language === "hi" ? "एकीकृत इनबॉक्स" : "Unified inbox"}</p>
          <h1>{t.inboxTitle}</h1>
          <p>{t.inboxSub}</p>
        </div>
        <div className="head-action-row">
          <span className="count-pill">
            {(stats?.unread || 0).toLocaleString()} {t.filterUnread.toLowerCase()}
          </span>
          <button type="button" className="btn ghost" onClick={onRefresh} disabled={loading}>
            <RefreshIcon size={16} />
            {t.refresh}
          </button>
        </div>
      </header>

      <section className="panel inbox-panel">
        <div className="inbox-toolbar">
          <label className="search-box">
            <SearchIcon size={16} />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t.searchInbox}
              aria-label={t.searchInbox}
            />
            {query && (
              <button type="button" className="clear-search" onClick={() => setQuery("")}>
                <XIcon size={13} />
              </button>
            )}
          </label>
          <div className="filter-row">
            {filters.map(([id, label]) => (
              <button
                type="button"
                key={id}
                className={`filter-chip ${filter === id ? "active" : ""}`}
                onClick={() => setFilter(id)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {visible.length === 0 ? (
          <div className="empty-state with-icon">
            <InboxIcon size={24} />
            <p>{messages.length === 0 ? t.noMessages : t.noMessages}</p>
            <button type="button" className="btn subtle" onClick={onRefresh}>
              {t.syncNow}
            </button>
          </div>
        ) : (
          <ul className="message-list">
            {visible.map((message) => (
              <li key={message.id}>
                <button
                  type="button"
                  className={`message-row ${message.unread ? "unread" : ""}`}
                  onClick={() => openMessage(message)}
                >
                  <span className={`message-avatar ${message.source}`}>
                    {message.source === "whatsapp" ? (
                      <WhatsAppIcon size={17} />
                    ) : (
                      <span>{initials(message.sender_name || message.sender)}</span>
                    )}
                  </span>
                  <span className="message-main">
                    <span className="message-top">
                      <strong>{message.sender_name || message.sender || sourceLabel(t, message.source)}</strong>
                      <span className="message-source">
                        <SourceIcon source={message.source} size={12} />
                        {sourceLabel(t, message.source)}
                      </span>
                      <time>{relativeTime(message.received_at, language)}</time>
                    </span>
                    <span className="message-subject">{message.subject}</span>
                    <span className="message-snippet">
                      {message.summary || message.snippet}
                    </span>
                    <span className="message-badges">
                      {message.needs_action && (
                        <span className="tag accent">
                          <AlertIcon size={11} />
                          {t.needsAction}
                        </span>
                      )}
                      {message.category && message.category !== "other" && (
                        <span className="tag">{message.category}</span>
                      )}
                      {message.priority === "urgent" && <span className="tag bad">urgent</span>}
                      {message.priority === "high" && <span className="tag warn">high</span>}
                      {message.deadline_id && (
                        <span className="tag good">
                          <ClockIcon size={11} />
                          deadline
                        </span>
                      )}
                    </span>
                  </span>
                  {message.unread && <span className="unread-dot" />}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {detail && (
        <div className="detail-layer" role="dialog" aria-label={detail.subject}>
          <button
            type="button"
            className="detail-backdrop"
            aria-label="Close"
            onClick={() => setDetail(null)}
          />
          <article className="message-detail">
            <header>
              <div>
                <p className="eyebrow">
                  {sourceLabel(t, detail.source)} · {relativeTime(detail.received_at, language)}
                </p>
                <h2>{detail.subject}</h2>
                <p className="detail-sender">
                  {detail.sender_name || detail.sender}
                  {detail.sender_name && detail.sender ? ` · ${detail.sender}` : ""}
                </p>
              </div>
              <button type="button" className="icon-btn" onClick={() => setDetail(null)}>
                <XIcon size={16} />
              </button>
            </header>

            <div className="detail-tags">
              {detail.category && detail.category !== "other" && (
                <span className="tag">{detail.category}</span>
              )}
              {detail.priority && detail.priority !== "normal" && (
                <span className={`tag ${detail.priority === "urgent" ? "bad" : "warn"}`}>
                  {detail.priority}
                </span>
              )}
              {detail.needs_action && (
                <span className="tag accent">
                  <AlertIcon size={11} />
                  {t.needsAction}
                </span>
              )}
            </div>

            <div className={`detail-body ${detailLoading ? "loading" : ""}`}>
              {detailLoading ? <span className="typing-line" /> : detail.body || detail.snippet}
            </div>

            {Array.isArray(detail.flags) && detail.flags.length > 0 && (
              <div className="flag-inline">
                <AlertIcon size={14} />
                <span>{t.flagBody}</span>
              </div>
            )}

            <footer className="detail-actions">
              {detail.unread && (
                <button
                  type="button"
                  className="btn ghost"
                  onClick={async () => {
                    await onMarkRead(detail.id, true);
                    setDetail({ ...detail, unread: false });
                  }}
                >
                  <CheckIcon size={15} />
                  {t.markRead}
                </button>
              )}
              <button
                type="button"
                className="btn primary"
                onClick={() => {
                  const prompt =
                    language === "hi"
                      ? `इस संदेश का सारांश दो: "${detail.subject}" — ${detail.sender_name || detail.sender}`
                      : `Summarize this message and tell me if I need to act: "${detail.subject}" — from ${detail.sender_name || detail.sender}`;
                  setDetail(null);
                  onAsk(prompt);
                }}
              >
                <SparkIcon size={15} />
                {t.askAbout}
                <ArrowRightIcon size={14} />
              </button>
            </footer>
          </article>
        </div>
      )}
    </div>
  );
}
