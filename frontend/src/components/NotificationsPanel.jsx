import { BellIcon, CheckIcon, ClockIcon, XIcon } from "../icons";

function timeLabel(ts, language) {
  try {
    return new Intl.DateTimeFormat(language === "hi" ? "hi-IN" : "en-IN", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(ts));
  } catch {
    return ts;
  }
}

export function NotificationsPanel({
  t,
  language,
  notifications,
  unread,
  open,
  onClose,
  onRead,
  onReadAll,
  onOpenNotification,
}) {
  if (!open) return null;

  return (
    <>
      <button
        type="button"
        className="notif-backdrop"
        aria-label="Close notifications"
        onClick={onClose}
      />
      <aside className="notif-panel" role="dialog" aria-label={t.notifications}>
        <header className="notif-head">
          <div>
            <p className="eyebrow">{unread ? `${unread} new` : t.filterAll}</p>
            <h2>{t.notifications}</h2>
          </div>
          <div className="notif-head-actions">
            {unread > 0 && (
              <button type="button" className="mini-btn" onClick={onReadAll}>
                <CheckIcon size={13} />
                {t.markAllRead}
              </button>
            )}
            <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
              <XIcon size={16} />
            </button>
          </div>
        </header>

        {notifications.length === 0 ? (
          <div className="empty-state with-icon">
            <BellIcon size={22} />
            <p>{t.noNotifications}</p>
          </div>
        ) : (
          <ul className="notif-list">
            {notifications.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className={`notif-item ${item.read ? "" : "unread"} ${item.kind || "info"}`}
                  onClick={() => onOpenNotification(item)}
                >
                  <span className={`notif-dot ${item.kind || "info"}`} />
                  <span className="notif-copy">
                    <strong>{item.title}</strong>
                    {item.body && <span>{item.body}</span>}
                    <time>
                      <ClockIcon size={11} />
                      {timeLabel(item.ts, language)}
                    </time>
                  </span>
                  {!item.read && (
                    <span
                      className="notif-read"
                      role="button"
                      tabIndex={0}
                      title={t.markRead}
                      onClick={(event) => {
                        event.stopPropagation();
                        onRead(item.id);
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.stopPropagation();
                          onRead(item.id);
                        }
                      }}
                    >
                      <CheckIcon size={13} />
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </>
  );
}
