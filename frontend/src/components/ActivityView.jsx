import { ActionCard } from "./ActionCard";
import { COPY } from "../i18n";
import {
  CheckIcon,
  ShieldIcon,
  UndoIcon,
  XIcon,
  AlertIcon,
  SparkIcon,
  RefreshIcon,
} from "../icons";

function iconFor(event) {
  if (event === "action.executed") return CheckIcon;
  if (event === "action.rejected") return XIcon;
  if (event === "action.undone") return UndoIcon;
  if (event.startsWith("guardrail")) return AlertIcon;
  if (event.startsWith("action")) return ShieldIcon;
  return SparkIcon;
}

function toneFor(event) {
  if (event === "action.executed") return "good";
  if (event === "action.rejected" || event === "action.failed") return "bad";
  if (event.startsWith("guardrail")) return "warn";
  return "neutral";
}

export function ActivityView({
  t,
  language,
  pendingActions,
  actionMap,
  audit,
  loading,
  actionBusy,
  onApprove,
  onReject,
  onUndo,
  onRefresh,
}) {
  const locale = language === "hi" ? "hi-IN" : "en-IN";
  const time = (ts) => {
    try {
      return new Intl.DateTimeFormat(locale, {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date(ts));
    } catch {
      return ts;
    }
  };

  return (
    <div className="page activity-page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Approval gate · Audit</p>
          <h1>{t.activityTitle}</h1>
          <p>{t.activitySub}</p>
        </div>
        <button type="button" className="btn ghost" onClick={onRefresh} disabled={loading}>
          <RefreshIcon size={16} />
          {t.refresh}
        </button>
      </header>

      <section className="panel" aria-labelledby="pending-title">
        <header className="panel-head">
          <div>
            <p className="eyebrow">{language === "hi" ? "अप्रूवल गेट" : "Approval gate"}</p>
            <h2 id="pending-title">{t.pendingSection}</h2>
          </div>
          <span className="count-pill">{pendingActions.length}</span>
        </header>
        {pendingActions.length === 0 ? (
          <div className="empty-state with-icon">
            <ShieldIcon size={22} />
            <p>{t.emptyPending}</p>
          </div>
        ) : (
          <div className="cards">
            {pendingActions.map((action) => (
              <ActionCard
                key={action.id}
                action={action}
                language={language}
                onApprove={onApprove}
                onReject={onReject}
                onUndo={onUndo}
                busy={Boolean(actionBusy[action.id])}
              />
            ))}
          </div>
        )}
      </section>

      <section className="panel" aria-labelledby="audit-title">
        <header className="panel-head">
          <div>
            <p className="eyebrow">{language === "hi" ? "ऑडिट ट्रेल" : "Audit trail"}</p>
            <h2 id="audit-title">{t.auditSection}</h2>
          </div>
          <span className="count-pill">{audit.length}</span>
        </header>
        {audit.length === 0 ? (
          <p className="empty-state">{t.emptyAudit}</p>
        ) : (
          <ol className="timeline">
            {audit.map((entry) => {
              const Icon = iconFor(entry.event);
              const action = entry.action_id ? actionMap[entry.action_id] : null;
              const detail =
                entry.detail?.title ||
                entry.detail?.request ||
                entry.detail?.reason ||
                entry.detail?.intent ||
                entry.detail?.error ||
                "";
              const undoable = entry.event === "action.executed" && action?.undoable;
              return (
                <li key={entry.id} className={`timeline-item ${toneFor(entry.event)}`}>
                  <span className="timeline-icon">
                    <Icon size={15} />
                  </span>
                  <div className="timeline-body">
                    <strong>{t.audit[entry.event] || entry.event}</strong>
                    {detail && <span className="timeline-detail">{detail}</span>}
                    <time>{time(entry.ts)}</time>
                  </div>
                  {undoable && (
                    <button
                      type="button"
                      className="mini-btn"
                      onClick={() => onUndo(action.id)}
                      disabled={Boolean(actionBusy[action.id])}
                    >
                      <UndoIcon size={13} />
                      {t.undo}
                    </button>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </section>

      <footer className="page-footer">
        <span>
          <ShieldIcon size={14} />
          {language === "hi"
            ? "हर राइट ऑपरेशन अप्रूवल गेट से गुज़रता है।"
            : "Every write passes through the approval gate."}
        </span>
        <span className="footer-dot">·</span>
        <span>{t.footerNote}</span>
      </footer>
    </div>
  );
}
