import { CalendarIcon, CheckIcon, DriveIcon, MailIcon, ShieldIcon, UndoIcon, XIcon } from "../icons";
import { COPY, statusLabel } from "../i18n";

export function ActionCard({ action, language, onApprove, onReject, onUndo, busy }) {
  const t = COPY[language];
  const preview = action.preview || {};
  const isCalendar = action.tool.startsWith("calendar");
  const isGmail = action.tool.startsWith("gmail");
  const ToolIcon = isCalendar ? CalendarIcon : isGmail ? MailIcon : DriveIcon;
  const toolLabel = isCalendar ? t.toolCalendar : isGmail ? t.toolGmail : t.toolDrive;
  const status = action.status;

  return (
    <article className={`action-card status-${status}`} aria-busy={busy}>
      <header className="action-head">
        <span className="tool-pill">
          <ToolIcon size={14} />
          {toolLabel}
        </span>
        <span className={`status-pill ${status}`}>{statusLabel(language, status)}</span>
      </header>
      <h3>{preview.title || action.tool}</h3>
      {preview.summary && <p className="action-summary">{preview.summary}</p>}
      {preview.fields?.length > 0 && (
        <dl className="action-fields">
          {preview.fields.map((field) => (
            <div
              className={field.label === "Body" ? "field field-body" : "field"}
              key={`${field.label}-${field.value}`}
            >
              <dt>{field.label}</dt>
              <dd>{field.label === "Body" ? <pre>{field.value}</pre> : field.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {preview.note && (
        <p className="action-note">
          <ShieldIcon size={14} />
          {preview.note}
        </p>
      )}
      {status === "pending" && (
        <div className="action-buttons">
          <button
            type="button"
            className="btn primary"
            onClick={() => onApprove(action.id)}
            disabled={busy}
          >
            <CheckIcon size={16} />
            {t.approve}
          </button>
          <button
            type="button"
            className="btn ghost"
            onClick={() => onReject(action.id)}
            disabled={busy}
          >
            <XIcon size={16} />
            {t.reject}
          </button>
        </div>
      )}
      {status === "executed" && action.undoable && (
        <div className="action-buttons">
          <span className="done-note">
            <CheckIcon size={14} />
            {t.status.executed}
          </span>
          <button type="button" className="btn subtle" onClick={() => onUndo(action.id)} disabled={busy}>
            <UndoIcon size={15} />
            {t.undo}
          </button>
        </div>
      )}
      {status === "executed" && !action.undoable && (
        <span className="done-note">
          <CheckIcon size={14} />
          {t.status.executed}
        </span>
      )}
      {status === "rejected" && <span className="muted-note">✕ {t.status.rejected}</span>}
      {status === "failed" && (
        <span className="muted-note danger">{action.result?.error || t.status.failed}</span>
      )}
    </article>
  );
}
