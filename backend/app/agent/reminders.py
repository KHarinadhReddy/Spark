from __future__ import annotations

from datetime import datetime
from typing import Any

from ..core.audit import AuditLog
from ..core.store import UnifiedStore


class ReminderService:
    """Materialises due reminders into the in-app notification centre.

    A future web-push channel can be added here without touching the scheduler:
    every reminder is already persisted with a channel and a fire time.
    """

    def __init__(self, store: UnifiedStore, audit: AuditLog) -> None:
        self.store = store
        self.audit = audit

    def run(self, now: datetime | None = None) -> dict[str, Any]:
        due = self.store.due_reminders(now)
        sent = 0
        for reminder in due:
            self.store.mark_reminder_sent(reminder["id"])
            title = f"Reminder: {reminder['title']}"
            body = self._body(reminder)
            self.store.add_notification(
                title,
                body,
                kind="reminder",
                source=reminder["source"],
                source_id=reminder["source_id"],
                meta={
                    "deadline_id": reminder["deadline_id"],
                    "priority": reminder["priority"],
                    "fire_at": reminder["fire_at"],
                },
            )
            sent += 1
        if sent:
            self.audit.log("reminders.sent", detail={"count": sent})
        return {"sent": sent, "due": len(due)}

    @staticmethod
    def _body(reminder: dict[str, Any]) -> str:
        due = reminder.get("due_date") or ""
        due_at = reminder.get("due_at") or ""
        when = due
        if due_at:
            try:
                when = datetime.fromisoformat(due_at).strftime("%d %b %Y, %I:%M %p")
            except ValueError:
                when = due_at
        parts = [f"Due {when}" if when else "Due soon"]
        if reminder.get("category"):
            parts.append(str(reminder["category"]).title())
        if reminder.get("evidence"):
            parts.append(str(reminder["evidence"])[:180])
        return " · ".join(parts)
