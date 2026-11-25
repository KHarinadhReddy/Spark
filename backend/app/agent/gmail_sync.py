from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import Settings
from ..core.audit import AuditLog
from ..core.store import Message, UnifiedStore
from ..mcp.google_workspace import GoogleWorkspace
from .extractor import classify_message
from .llm_client import LLMClient

INITIAL_QUERY = "newer_than:90d -in:chats"


class GmailSync:
    """Incremental Gmail sync into the unified store.

    Reads are free. No message is ever acted on automatically: deadlines become
    data rows, and any write (calendar event, draft) still goes through the
    approval gate.
    """

    def __init__(
        self,
        settings: Settings,
        store: UnifiedStore,
        audit: AuditLog,
        llm: LLMClient,
        workspace_getter,
    ) -> None:
        self.settings = settings
        self.store = store
        self.audit = audit
        self.llm = llm
        self._workspace_getter = workspace_getter
        self._running = False

    @property
    def workspace(self) -> Any:
        return self._workspace_getter()

    @property
    def available(self) -> bool:
        return isinstance(self.workspace, GoogleWorkspace)

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "last_sync": self.store.get_state("gmail.last_sync"),
            "last_error": self.store.get_state("gmail.last_error"),
            "synced": self.store.get_state("gmail.synced", 0),
        }

    def sync(self, *, limit: int = 60, force_initial: bool = False) -> dict[str, Any]:
        if not self.available:
            return {
                "ok": False,
                "reason": "Google is not connected; Spark is in demo mode.",
                "synced": 0,
            }
        if self._running:
            return {"ok": False, "reason": "sync already running", "synced": 0}
        self._running = True
        started = datetime.now(timezone.utc)
        try:
            workspace: GoogleWorkspace = self.workspace
            last_sync = self.store.get_state("gmail.last_sync")
            if force_initial or not last_sync:
                query = INITIAL_QUERY
            else:
                try:
                    last = datetime.fromisoformat(last_sync)
                except ValueError:
                    last = started - timedelta(days=3)
                after = (last - timedelta(days=2)).strftime("%Y/%m/%d")
                query = f"after:{after} -in:chats"
            listing = workspace.list_message_ids(query=query, limit=limit)
            new_count = 0
            deadline_count = 0
            notification_count = 0
            llm_budget = max(0, int(self.settings.llm_sync_budget))
            for message_id in listing.get("ids", []):
                if self.store.message_exists("gmail", message_id):
                    continue
                try:
                    full = workspace.get_message(message_id)
                except Exception:
                    continue
                extraction = classify_message(
                    full,
                    self.llm,
                    now=datetime.now().astimezone(),
                    timezone_name=self.settings.timezone,
                    allow_llm=llm_budget > 0,
                )
                if llm_budget > 0:
                    llm_budget -= 1
                deadline = None
                if extraction.is_deadline and extraction.deadline:
                    deadline, created = self.store.create_deadline(
                        source="gmail",
                        source_id=message_id,
                        title=extraction.deadline["title"],
                        due_date=extraction.deadline["due_date"],
                        due_at=extraction.deadline.get("due_at") or None,
                        category=extraction.category,
                        priority=extraction.priority,
                        confidence=float(extraction.deadline.get("confidence", 0.6)),
                        evidence=extraction.deadline.get("evidence", ""),
                        timezone_name=self.settings.timezone,
                    )
                    if created:
                        deadline_count += 1
                message = self.store.upsert_message(
                    {
                        "source": "gmail",
                        "external_id": message_id,
                        "thread_id": full.get("thread_id"),
                        "sender": full.get("from"),
                        "sender_name": full.get("from_name"),
                        "subject": full.get("subject"),
                        "snippet": full.get("snippet"),
                        "body": full.get("body", ""),
                        "received_at": full.get("date"),
                        "labels": full.get("labels", []),
                        "unread": full.get("unread", True),
                        "category": extraction.category,
                        "priority": extraction.priority,
                        "summary": extraction.summary,
                        "needs_action": extraction.needs_action,
                        "deadline_id": deadline.id if deadline else None,
                        "flags": extraction.flags,
                    }
                )
                new_count += 1
                if extraction.is_deadline and deadline and created:
                    self.store.add_notification(
                        f"New deadline: {deadline.title}",
                        f"Due {deadline.due_date}"
                        + (f" at {deadline.due_at[11:16]}" if deadline.due_at else ""),
                        kind="deadline",
                        source="gmail",
                        source_id=message_id,
                        meta={"deadline_id": deadline.id, "priority": deadline.priority},
                    )
                    notification_count += 1
                if (
                    not extraction.is_deadline
                    and extraction.important
                    and extraction.priority in {"urgent", "high"}
                ):
                    self.store.add_notification(
                        f"{extraction.priority.title()} message: {message.subject}",
                        extraction.summary,
                        kind="message",
                        source="gmail",
                        source_id=message_id,
                        meta={"category": extraction.category, "message_id": message.id},
                    )
                    notification_count += 1
            now = datetime.now(timezone.utc).isoformat()
            self.store.set_state("gmail.last_sync", now)
            self.store.set_state("gmail.last_error", None)
            self.store.set_state("gmail.synced", int(self.store.get_state("gmail.synced", 0)) + new_count)
            self.audit.log(
                "gmail.synced",
                tool="gmail.sync",
                detail={
                    "new": new_count,
                    "deadlines": deadline_count,
                    "notifications": notification_count,
                    "query": query,
                },
            )
            return {
                "ok": True,
                "new_messages": new_count,
                "new_deadlines": deadline_count,
                "notifications": notification_count,
                "query": query,
                "duration_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
            }
        except Exception as exc:
            self.store.set_state("gmail.last_error", str(exc)[:400])
            self.audit.log("gmail.sync_failed", tool="gmail.sync", detail={"error": str(exc)[:300]})
            return {"ok": False, "reason": str(exc)[:300], "synced": 0}
        finally:
            self._running = False

    def sync_for_message(self, message_id: str) -> Message | None:
        """Fetch one message immediately (used after a Google connect)."""
        if not self.available:
            return None
        try:
            full = self.workspace.get_message(message_id)
        except Exception:
            return None
        return self.store.upsert_message(
            {
                "source": "gmail",
                "external_id": message_id,
                "thread_id": full.get("thread_id"),
                "sender": full.get("from"),
                "sender_name": full.get("from_name"),
                "subject": full.get("subject"),
                "snippet": full.get("snippet"),
                "body": full.get("body", ""),
                "received_at": full.get("date"),
                "labels": full.get("labels", []),
                "unread": full.get("unread", True),
            }
        )
