from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .db import Database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:14]}"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip(" .,-–—")


_HTML_TAG = re.compile(r"<[^>]+>")
_HTML_ENT = {
    "nbsp": " ",
    "amp": "&",
    "lt": "<",
    "gt": ">",
    "quot": '"',
    "apos": "'",
}


def strip_html(text: str) -> str:
    """Collapse HTML / email-mime noise into plain readable text."""
    cleaned = _HTML_TAG.sub(" ", text or "")
    cleaned = re.sub(r"&([a-z]+);", lambda m: _HTML_ENT.get(m.group(1).lower(), m.group(0)), cleaned)
    cleaned = re.sub(r"<[^>]*>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


@dataclass(slots=True)
class Message:
    id: str
    source: str
    external_id: str
    thread_id: str
    sender: str
    sender_name: str
    subject: str
    snippet: str
    body: str
    received_at: str
    labels: list[str] = field(default_factory=list)
    category: str = "other"
    priority: str = "normal"
    summary: str = ""
    needs_action: bool = False
    deadline_id: str | None = None
    flags: list[dict[str, Any]] = field(default_factory=list)
    unread: bool = True
    archived: bool = False

    def public(self, include_body: bool = False) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "source": self.source,
            "external_id": self.external_id,
            "thread_id": self.thread_id,
            "sender": self.sender,
            "sender_name": self.sender_name,
            "subject": self.subject,
            "snippet": strip_html(self.snippet),
            "received_at": self.received_at,
            "labels": self.labels,
            "category": self.category,
            "priority": self.priority,
            "summary": self.summary,
            "needs_action": self.needs_action,
            "deadline_id": self.deadline_id,
            "flags": self.flags,
            "unread": self.unread,
            "archived": self.archived,
        }
        if include_body:
            payload["body"] = strip_html(self.body)
        return payload


@dataclass(slots=True)
class StoredDeadline:
    id: str
    source: str
    source_id: str
    title: str
    due_date: str
    due_at: str
    timezone: str
    category: str
    priority: str
    confidence: float
    evidence: str
    status: str
    created_at: str
    updated_at: str
    completed_at: str | None = None

    @property
    def due_date_value(self) -> date | None:
        if self.due_date:
            try:
                return date.fromisoformat(self.due_date[:10])
            except ValueError:
                return None
        if self.due_at:
            try:
                return datetime.fromisoformat(self.due_at).date()
            except ValueError:
                return None
        return None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email_id": self.source_id,  # legacy field used by the current UI
            "source": self.source,
            "source_id": self.source_id,
            "title": self.title,
            "subject": self.title,
            "date": (self.due_date or self.due_at or "")[:10],
            "due_at": self.due_at,
            "timezone": self.timezone,
            "category": self.category,
            "priority": self.priority,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class Notification:
    id: str
    ts: str
    title: str
    body: str
    kind: str
    source: str
    source_id: str
    read: bool
    meta: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "title": self.title,
            "body": self.body,
            "kind": self.kind,
            "source": self.source,
            "source_id": self.source_id,
            "read": self.read,
            "meta": self.meta,
        }


class UnifiedStore:
    """SQLite-backed inbox, deadlines, reminders, notifications and memory."""

    def __init__(self, db: Database, timezone_name: str = "Asia/Kolkata") -> None:
        self.db = db
        self.timezone_name = timezone_name
        try:
            self.tz = ZoneInfo(timezone_name)
        except Exception:
            self.tz = timezone(timedelta(hours=5, minutes=30))

    # ------------------------------------------------------------------ setup
    def ensure_defaults(self) -> None:
        row = self.db.query_one("SELECT id FROM profiles WHERE id = 'owner'")
        if not row:
            self.save_profile(
                {
                    "name": "",
                    "email": "",
                    "phone": "",
                    "college": "",
                    "course": "",
                    "branch": "",
                    "graduation_year": "",
                    "address": "",
                    "city": "",
                    "state": "",
                    "pincode": "",
                    "linkedin": "",
                    "github": "",
                    "portfolio": "",
                    "skills": "",
                    "summary": "",
                }
            )

    # ----------------------------------------------------------------- inbox
    def upsert_message(self, data: dict[str, Any]) -> Message:
        source = (data.get("source") or "gmail").strip()
        external_id = str(data.get("external_id") or data.get("id") or "").strip()
        if not external_id:
            external_id = _hash(_json(data))[:20]
        existing = self.db.query_one(
            "SELECT * FROM messages WHERE source = ? AND external_id = ?",
            (source, external_id),
        )
        message_id = existing["id"] if existing else _id("msg")
        now = _now()
        values = {
            "id": message_id,
            "source": source,
            "external_id": external_id,
            "thread_id": data.get("thread_id") or external_id,
            "sender": data.get("sender") or data.get("from") or "",
            "sender_name": data.get("sender_name") or data.get("from_name") or "",
            "subject": data.get("subject") or "(no subject)",
            "snippet": strip_html(data.get("snippet") or ""),
            "body": strip_html(data.get("body") or data.get("snippet") or ""),
            "received_at": data.get("received_at") or data.get("date") or now,
            "labels": _json(data.get("labels") or []),
            "category": data.get("category") or "other",
            "priority": data.get("priority") or "normal",
            "summary": data.get("summary") or "",
            "needs_action": 1 if data.get("needs_action") else 0,
            "deadline_id": data.get("deadline_id"),
            "flags": _json(data.get("flags") or []),
            "unread": 1 if data.get("unread", True) else 0,
            "archived": 1 if data.get("archived") else 0,
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        }
        self.db.execute(
            """INSERT INTO messages
               (id, source, external_id, thread_id, sender, sender_name, subject, snippet, body,
                received_at, labels, category, priority, summary, needs_action, deadline_id, flags,
                unread, archived, created_at, updated_at)
               VALUES (:id, :source, :external_id, :thread_id, :sender, :sender_name, :subject,
                       :snippet, :body, :received_at, :labels, :category, :priority, :summary,
                       :needs_action, :deadline_id, :flags, :unread, :archived, :created_at, :updated_at)
               ON CONFLICT(source, external_id) DO UPDATE SET
                 thread_id=excluded.thread_id,
                 sender=excluded.sender,
                 sender_name=excluded.sender_name,
                 subject=excluded.subject,
                 snippet=excluded.snippet,
                 body=excluded.body,
                 received_at=excluded.received_at,
                 labels=excluded.labels,
                 category=excluded.category,
                 priority=excluded.priority,
                 summary=excluded.summary,
                 needs_action=excluded.needs_action,
                 deadline_id=COALESCE(excluded.deadline_id, messages.deadline_id),
                 flags=excluded.flags,
                 unread=excluded.unread,
                 archived=excluded.archived,
                 updated_at=excluded.updated_at""",
            values,
        )
        return self.get_message(message_id)

    def get_message(self, message_id: str) -> Message:
        row = self.db.query_one("SELECT * FROM messages WHERE id = ?", (message_id,))
        if not row:
            raise KeyError(f"message not found: {message_id}")
        return self._message_from_row(row)

    def get_message_by_external(self, source: str, external_id: str) -> Message | None:
        row = self.db.query_one(
            "SELECT * FROM messages WHERE source = ? AND external_id = ?",
            (source, external_id),
        )
        return self._message_from_row(row) if row else None

    def message_exists(self, source: str, external_id: str) -> bool:
        row = self.db.query_one(
            "SELECT 1 AS found FROM messages WHERE source = ? AND external_id = ?",
            (source, external_id),
        )
        return bool(row)

    def list_messages(
        self,
        *,
        source: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        unread: bool | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Message]:
        clauses: list[str] = ["archived = 0"]
        params: list[Any] = []
        if source:
            clauses.append("source = ?")
            params.append(source)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        if unread is not None:
            clauses.append("unread = ?")
            params.append(1 if unread else 0)
        if query:
            like = f"%{query}%"
            clauses.append("(subject LIKE ? OR sender LIKE ? OR sender_name LIKE ? OR body LIKE ?)")
            params.extend([like, like, like, like])
        params.extend([int(limit), int(offset)])
        rows = self.db.query_all(
            f"SELECT * FROM messages WHERE {' AND '.join(clauses)} "
            "ORDER BY received_at DESC LIMIT ? OFFSET ?",
            tuple(params),
        )
        return [self._message_from_row(row) for row in rows]

    def search_messages(self, query: str, limit: int = 20, source: str | None = None) -> list[Message]:
        return self.list_messages(query=query, source=source, limit=limit)

    def mark_message_read(self, message_id: str, read: bool = True) -> None:
        self.db.execute(
            "UPDATE messages SET unread = ?, updated_at = ? WHERE id = ?",
            (0 if read else 1, _now(), message_id),
        )

    def inbox_stats(self) -> dict[str, int]:
        row = self.db.query_one(
            """SELECT
                 COUNT(*) AS total,
                 SUM(CASE WHEN unread = 1 THEN 1 ELSE 0 END) AS unread,
                 SUM(CASE WHEN needs_action = 1 THEN 1 ELSE 0 END) AS needs_action,
                 SUM(CASE WHEN priority = 'urgent' THEN 1 ELSE 0 END) AS urgent
               FROM messages WHERE archived = 0"""
        )
        return {key: int(row[key] or 0) for key in ("total", "unread", "needs_action", "urgent")}

    # -------------------------------------------------------------- deadlines
    def create_deadline(
        self,
        *,
        source: str,
        source_id: str,
        title: str,
        due_date: str | None,
        due_at: str | None = None,
        category: str = "general",
        priority: str = "normal",
        confidence: float = 0.6,
        evidence: str = "",
        timezone_name: str | None = None,
    ) -> tuple[StoredDeadline, bool]:
        due_date = (due_date or (due_at or "")[:10]) or ""
        dedupe = _hash(f"{_norm(title)}|{due_date}")
        existing = self.db.query_one(
            "SELECT * FROM deadlines WHERE dedupe_key = ? AND status IN ('active','snoozed') "
            "ORDER BY created_at LIMIT 1",
            (dedupe,),
        )
        now = _now()
        if existing:
            self.db.execute(
                """UPDATE deadlines SET source = ?, source_id = ?, title = ?, due_date = ?,
                   due_at = COALESCE(?, due_at), category = ?, priority = ?, confidence = ?,
                   evidence = ?, updated_at = ? WHERE id = ?""",
                (
                    source,
                    source_id,
                    title,
                    due_date,
                    due_at,
                    category,
                    priority,
                    float(confidence),
                    evidence,
                    now,
                    existing["id"],
                ),
            )
            deadline = self.get_deadline(existing["id"])
            self.schedule_default_reminders(deadline)
            return deadline, False

        deadline_id = _id("dl")
        self.db.execute(
            """INSERT INTO deadlines
               (id, source, source_id, title, due_date, due_at, timezone, category, priority,
                confidence, evidence, status, dedupe_key, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)""",
            (
                deadline_id,
                source,
                source_id,
                title,
                due_date,
                due_at,
                timezone_name or self.timezone_name,
                category,
                priority,
                float(confidence),
                evidence,
                dedupe,
                now,
                now,
            ),
        )
        deadline = self.get_deadline(deadline_id)
        self.schedule_default_reminders(deadline)
        return deadline, True

    def get_deadline(self, deadline_id: str) -> StoredDeadline:
        row = self.db.query_one("SELECT * FROM deadlines WHERE id = ?", (deadline_id,))
        if not row:
            raise KeyError(f"deadline not found: {deadline_id}")
        return self._deadline_from_row(row)

    def list_deadlines(
        self,
        *,
        status: str | None = "active",
        days: int | None = None,
        limit: int = 100,
    ) -> list[StoredDeadline]:
        clauses: list[str] = []
        params: list[Any] = []
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        if days is not None:
            end = date.today() + timedelta(days=int(days))
            clauses.append("(due_date = '' OR due_date <= ?)")
            params.append(end.isoformat())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        rows = self.db.query_all(
            f"SELECT * FROM deadlines {where} ORDER BY due_date ASC, due_at ASC LIMIT ?",
            tuple(params),
        )
        return [self._deadline_from_row(row) for row in rows]

    def update_deadline_status(self, deadline_id: str, status: str) -> StoredDeadline:
        completed = _now() if status == "completed" else None
        self.db.execute(
            "UPDATE deadlines SET status = ?, completed_at = ?, updated_at = ? WHERE id = ?",
            (status, completed, _now(), deadline_id),
        )
        return self.get_deadline(deadline_id)

    def find_deadline_by_source(self, source: str, source_id: str) -> StoredDeadline | None:
        row = self.db.query_one(
            "SELECT * FROM deadlines WHERE source = ? AND source_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (source, source_id),
        )
        return self._deadline_from_row(row) if row else None

    # --------------------------------------------------------------- reminders
    def schedule_default_reminders(self, deadline: StoredDeadline) -> int:
        due = self._deadline_moment(deadline)
        if due is None:
            return 0
        now = datetime.now(self.tz)
        existing = {
            row["fire_at"]
            for row in self.db.query_all(
                "SELECT fire_at FROM reminders WHERE deadline_id = ?", (deadline.id,)
            )
        }
        fire_times: list[datetime] = []
        for days in (7, 3, 1, 0):
            moment = datetime.combine(due.date() - timedelta(days=days), time(9, 0), tzinfo=self.tz)
            if moment > now:
                fire_times.append(moment)
        if due.hour or due.minute:
            two_hours = due - timedelta(hours=2)
            if two_hours > now:
                fire_times.append(two_hours)
        if not fire_times and due > now:
            fire_times.append(min(due, now + timedelta(minutes=1)))
        created = 0
        for moment in sorted(set(fire_times)):
            fire_at = moment.isoformat(timespec="minutes")
            if fire_at in existing:
                continue
            self.db.execute(
                """INSERT INTO reminders (id, deadline_id, channel, fire_at, status, created_at)
                   VALUES (?, ?, 'in-app', ?, 'scheduled', ?)""",
                (_id("rem"), deadline.id, fire_at, _now()),
            )
            created += 1
        return created

    def due_reminders(self, now: datetime | None = None) -> list[dict[str, Any]]:
        moment = (now or datetime.now(self.tz)).isoformat(timespec="minutes")
        rows = self.db.query_all(
            """SELECT r.*, d.title, d.due_date, d.due_at, d.priority, d.category, d.source,
                      d.source_id, d.evidence
               FROM reminders r JOIN deadlines d ON d.id = r.deadline_id
               WHERE r.status = 'scheduled' AND r.fire_at <= ? AND d.status = 'active'
               ORDER BY r.fire_at ASC""",
            (moment,),
        )
        return [dict(row) for row in rows]

    def mark_reminder_sent(self, reminder_id: str) -> None:
        self.db.execute(
            "UPDATE reminders SET status = 'sent', sent_at = ? WHERE id = ?",
            (_now(), reminder_id),
        )

    def snooze_deadline(self, deadline_id: str, days: int = 1) -> StoredDeadline:
        deadline = self.get_deadline(deadline_id)
        due = self._deadline_moment(deadline)
        if due:
            due = due + timedelta(days=days)
            self.db.execute(
                "UPDATE deadlines SET due_date = ?, due_at = ?, status = 'active', updated_at = ? WHERE id = ?",
                (due.date().isoformat(), due.isoformat(timespec="minutes"), _now(), deadline_id),
            )
            self.schedule_default_reminders(self.get_deadline(deadline_id))
        return self.get_deadline(deadline_id)

    # ----------------------------------------------------------- notifications
    def add_notification(
        self,
        title: str,
        body: str = "",
        *,
        kind: str = "info",
        source: str = "",
        source_id: str = "",
        meta: dict[str, Any] | None = None,
    ) -> Notification:
        notification = Notification(
            id=_id("notif"),
            ts=_now(),
            title=title,
            body=body,
            kind=kind,
            source=source,
            source_id=source_id,
            read=False,
            meta=meta or {},
        )
        self.db.execute(
            """INSERT INTO notifications (id, ts, title, body, kind, source, source_id, read, meta)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (
                notification.id,
                notification.ts,
                notification.title,
                notification.body,
                notification.kind,
                notification.source,
                notification.source_id,
                _json(notification.meta),
            ),
        )
        return notification

    def list_notifications(self, limit: int = 50, unread_only: bool = False) -> list[Notification]:
        clause = "WHERE read = 0" if unread_only else ""
        rows = self.db.query_all(
            f"SELECT * FROM notifications {clause} ORDER BY ts DESC LIMIT ?", (int(limit),)
        )
        return [self._notification_from_row(row) for row in rows]

    def mark_notification_read(self, notification_id: str) -> None:
        self.db.execute("UPDATE notifications SET read = 1 WHERE id = ?", (notification_id,))

    def mark_all_notifications_read(self) -> None:
        self.db.execute("UPDATE notifications SET read = 1 WHERE read = 0")

    def unread_notifications(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS count FROM notifications WHERE read = 0")
        return int(row["count"] if row else 0)

    # ---------------------------------------------------------------- profiles
    def get_profile(self) -> dict[str, Any]:
        row = self.db.query_one("SELECT data FROM profiles WHERE id = 'owner'")
        return _loads(row["data"], {}) if row else {}

    def save_profile(self, data: dict[str, Any]) -> dict[str, Any]:
        self.db.execute(
            "INSERT INTO profiles (id, data, updated_at) VALUES ('owner', ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
            (_json(data), _now()),
        )
        return self.get_profile()

    # ----------------------------------------------------------- conversations
    def add_turn(self, role: str, content: str, meta: dict[str, Any] | None = None) -> None:
        self.db.execute(
            "INSERT INTO conversations (id, ts, role, content, meta) VALUES (?, ?, ?, ?, ?)",
            (_id("turn"), _now(), role, content, _json(meta or {})),
        )

    def history(self, limit: int = 24) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            "SELECT * FROM conversations ORDER BY ts DESC LIMIT ?", (int(limit),)
        )
        return [
            {"role": row["role"], "content": row["content"], "ts": row["ts"], "meta": _loads(row["meta"], {})}
            for row in reversed(rows)
        ]

    def clear_history(self) -> None:
        self.db.execute("DELETE FROM conversations")

    # ------------------------------------------------------------- sync state
    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.db.query_one("SELECT value FROM sync_state WHERE key = ?", (key,))
        return _loads(row["value"], default) if row else default

    def set_state(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO sync_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, _json(value), _now()),
        )

    # -------------------------------------------------------------- companions
    def create_companion(self, name: str, platform: str, token: str) -> dict[str, Any]:
        device_id = _id("dev")
        self.db.execute(
            """INSERT INTO companion_devices (id, name, platform, token_hash, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (device_id, name or "Android", platform or "android", _hash(token), _now()),
        )
        return {"id": device_id, "name": name, "platform": platform, "token": token}

    def find_companion(self, token: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM companion_devices WHERE token_hash = ?", (_hash(token),)
        )
        if not row:
            return None
        self.db.execute(
            "UPDATE companion_devices SET last_seen = ? WHERE id = ?", (_now(), row["id"])
        )
        return dict(row)

    def list_companions(self) -> list[dict[str, Any]]:
        rows = self.db.query_all("SELECT * FROM companion_devices ORDER BY created_at DESC")
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "platform": row["platform"],
                "last_seen": row["last_seen"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def delete_companion(self, device_id: str) -> None:
        self.db.execute("DELETE FROM companion_devices WHERE id = ?", (device_id,))

    # -------------------------------------------------------------- form audit
    def log_form(
        self,
        *,
        url: str,
        site: str,
        fields: int,
        submitted: bool,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.db.execute(
            """INSERT INTO form_audit (id, ts, url, site, fields, submitted, detail)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (_id("form"), _now(), url, site, int(fields), 1 if submitted else 0, _json(detail or {})),
        )

    # ------------------------------------------------------------------- stats
    def stats(self) -> dict[str, Any]:
        deadlines = self.db.query_one(
            "SELECT COUNT(*) AS count FROM deadlines WHERE status = 'active'"
        )
        return {
            **self.inbox_stats(),
            "deadlines_active": int(deadlines["count"] if deadlines else 0),
            "notifications_unread": self.unread_notifications(),
        }

    def purge_old(self, retention_days: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=int(retention_days))).isoformat()
        before = self.db.query_one("SELECT COUNT(*) AS count FROM messages WHERE received_at < ?", (cutoff,))
        self.db.execute("DELETE FROM messages WHERE received_at < ?", (cutoff,))
        self.db.execute("DELETE FROM notifications WHERE ts < ?", (cutoff,))
        self.db.execute("DELETE FROM conversations WHERE ts < ?", (cutoff,))
        return int(before["count"] if before else 0)

    # ---------------------------------------------------------------- internal
    def _deadline_moment(self, deadline: StoredDeadline) -> datetime | None:
        try:
            if deadline.due_at:
                moment = datetime.fromisoformat(deadline.due_at)
                if moment.tzinfo is None:
                    moment = moment.replace(tzinfo=self.tz)
                return moment.astimezone(self.tz)
            if deadline.due_date:
                return datetime.combine(
                    date.fromisoformat(deadline.due_date[:10]), time(9, 0), tzinfo=self.tz
                )
        except ValueError:
            return None
        return None

    @staticmethod
    def _message_from_row(row: Any) -> Message:
        return Message(
            id=row["id"],
            source=row["source"],
            external_id=row["external_id"],
            thread_id=row["thread_id"] or "",
            sender=row["sender"] or "",
            sender_name=row["sender_name"] or "",
            subject=row["subject"] or "",
            snippet=row["snippet"] or "",
            body=row["body"] or "",
            received_at=row["received_at"] or "",
            labels=_loads(row["labels"], []),
            category=row["category"] or "other",
            priority=row["priority"] or "normal",
            summary=row["summary"] or "",
            needs_action=bool(row["needs_action"]),
            deadline_id=row["deadline_id"],
            flags=_loads(row["flags"], []),
            unread=bool(row["unread"]),
            archived=bool(row["archived"]),
        )

    @staticmethod
    def _deadline_from_row(row: Any) -> StoredDeadline:
        return StoredDeadline(
            id=row["id"],
            source=row["source"],
            source_id=row["source_id"] or "",
            title=row["title"],
            due_date=row["due_date"] or "",
            due_at=row["due_at"] or "",
            timezone=row["timezone"] or "",
            category=row["category"] or "general",
            priority=row["priority"] or "normal",
            confidence=float(row["confidence"] or 0),
            evidence=row["evidence"] or "",
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _notification_from_row(row: Any) -> Notification:
        return Notification(
            id=row["id"],
            ts=row["ts"],
            title=row["title"],
            body=row["body"] or "",
            kind=row["kind"] or "info",
            source=row["source"] or "",
            source_id=row["source_id"] or "",
            read=bool(row["read"]),
            meta=_loads(row["meta"], {}),
        )
