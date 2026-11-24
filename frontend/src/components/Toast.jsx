import { useEffect } from "react";
import { UndoIcon, XIcon } from "../icons";
import { COPY } from "../i18n";

export function Toast({ toast, onClose, onUndo, language }) {
  const t = COPY[language];

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(onClose, 7000);
    return () => window.clearTimeout(timer);
  }, [toast, onClose]);

  if (!toast) return null;

  return (
    <div className={`toast ${toast.tone || ""}`} role="status" aria-live="polite">
      <span className="toast-message">{toast.message}</span>
      {toast.undoId && (
        <button type="button" className="toast-undo" onClick={() => onUndo(toast.undoId)}>
          <UndoIcon size={15} />
          {t.undo}
        </button>
      )}
      <button type="button" className="toast-close" onClick={onClose} aria-label="Close">
        <XIcon size={15} />
      </button>
    </div>
  );
}
