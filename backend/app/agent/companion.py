from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime
from typing import Any

from ..config import Settings
from ..core.audit import AuditLog
from ..core.store import UnifiedStore
from .extractor import classify_message
from .llm_client import LLMClient

WHATSAPP_PACKAGES = {
    "com.whatsapp",
    "com.whatsapp.w4b",
    "com.whatsapp.whatsapp",
}

_EXPORT_LINE = re.compile(
    r"^\[?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?)\]?\s*[-–]?\s*([^:]{1,80}):\s*(.*)$",
    re.I,
)


class CompanionService:
    """Ingests Android notification-listener events and WhatsApp chat exports.

    The companion is read-only: it forwards notifications. Spark never sends a
    WhatsApp message. Android notification access is a user-granted OS permission.
    """

    def __init__(
        self,
        settings: Settings,
        store: UnifiedStore,
        llm: LLMClient,
        audit: AuditLog,
    ) -> None:
        self.settings = settings
        self.store = store
        self.llm = llm
        self.audit = audit

    # ----------------------------------------------------------------- pairing
    def pair(self, name: str = "Android phone", platform: str = "android") -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        device = self.store.create_companion(name, platform, token)
        self.audit.log("companion.paired", detail={"device": device["id"], "platform": platform})
        return {
            **device,
            "endpoint": f"{self.settings.public_base_url or self.settings.backend_url}/api/companion/notifications",
        }

    def authenticate(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        if self.settings.companion_token and secrets.compare_digest(
            token, self.settings.companion_token
        ):
            return {"id": "static", "name": "Static companion token", "platform": "companion"}
        return self.store.find_companion(token)

    def devices(self) -> list[dict[str, Any]]:
        return self.store.list_companions()

    def revoke(self, device_id: str) -> None:
        self.store.delete_companion(device_id)
        self.audit.log("companion.revoked", detail={"device": device_id})

    # ------------------------------------------------------------- notifications
    def ingest(self, payload: dict[str, Any]) -> dict[str, Any]:
        package = str(payload.get("package") or payload.get("app") or "").strip()
        app = str(payload.get("app") or package or "notification").strip()
        title = _clean(payload.get("title") or payload.get("chat") or app)
        text = _clean(
            payload.get("text")
            or payload.get("body")
            or payload.get("big_text")
            or payload.get("subtext")
            or ""
        )
        if not text and not title:
            return {"ok": False, "reason": "empty notification"}
        source = "whatsapp" if _is_whatsapp(package, app) else "notification"
        received = _received_at(payload.get("timestamp") or payload.get("time"))
        external_id = _event_id(source, package, title, text, received)
        existing = self.store.get_message_by_external(source, external_id)
        if existing:
            return {
                "ok": True,
                "duplicate": True,
                "message_id": existing.id,
                "category": existing.category,
                "priority": existing.priority,
            }

        subject = f"{app}: {title}" if title and title != app else app
        extraction = classify_message(
            {
                "subject": subject,
                "from_name": title or app,
                "body": text,
                "received_at": received,
            },
            self.llm,
            now=datetime.now().astimezone(),
            timezone_name=self.settings.timezone,
        )
        deadline_id = None
        if extraction.is_deadline and extraction.deadline:
            deadline, created = self.store.create_deadline(
                source=source,
                source_id=external_id,
                title=extraction.deadline["title"],
                due_date=extraction.deadline["due_date"],
                due_at=extraction.deadline.get("due_at") or None,
                category=extraction.category,
                priority=extraction.priority,
                confidence=float(extraction.deadline.get("confidence", 0.55)),
                evidence=extraction.deadline.get("evidence", ""),
                timezone_name=self.settings.timezone,
            )
            deadline_id = deadline.id
            if created:
                self.store.add_notification(
                    f"New deadline from {app}: {deadline.title}",
                    f"Due {deadline.due_date}",
                    kind="deadline",
                    source=source,
                    source_id=external_id,
                    meta={"deadline_id": deadline.id, "priority": deadline.priority},
                )
        message = self.store.upsert_message(
            {
                "source": source,
                "external_id": external_id,
                "thread_id": _event_id(source, package, title, "", ""),
                "sender": app,
                "sender_name": title or app,
                "subject": subject[:240],
                "snippet": text[:500],
                "body": text,
                "received_at": received,
                "labels": [package] if package else [],
                "category": extraction.category,
                "priority": extraction.priority,
                "summary": extraction.summary,
                "needs_action": extraction.needs_action,
                "deadline_id": deadline_id,
                "flags": extraction.flags,
            }
        )
        important = bool(
            extraction.important or extraction.priority in {"urgent", "high"} or deadline_id
        )
        if important and not deadline_id:
            self.store.add_notification(
                f"{app}: {title or 'Important message'}",
                extraction.summary,
                kind="message",
                source=source,
                source_id=external_id,
                meta={
                    "message_id": message.id,
                    "category": extraction.category,
                    "priority": extraction.priority,
                },
            )
        self.audit.log(
            "companion.notification",
            tool=source,
            detail={
                "app": app,
                "category": extraction.category,
                "priority": extraction.priority,
                "important": important,
                "deadline": bool(deadline_id),
            },
        )
        return {
            "ok": True,
            "message_id": message.id,
            "category": extraction.category,
            "priority": extraction.priority,
            "important": important,
            "deadline_id": deadline_id,
        }

    # -------------------------------------------------------------- chat export
    def import_export(self, text: str, filename: str = "whatsapp.txt") -> dict[str, Any]:
        lines = text.splitlines()
        parsed: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for line in lines:
            match = _EXPORT_LINE.match(line.strip())
            if match:
                if current:
                    parsed.append(current)
                date_raw, time_raw, sender, message = match.groups()
                current = {
                    "date": date_raw,
                    "time": time_raw,
                    "sender": sender.strip(),
                    "text": message.strip(),
                }
            elif current and line.strip():
                current["text"] += "\n" + line.strip()
        if current:
            parsed.append(current)
        parsed = [item for item in parsed if item["text"]][-1000:]
        stored = 0
        deadlines = 0
        for index, item in enumerate(parsed):
            received = _parse_export_datetime(item["date"], item["time"])
            body = item["text"][:4000]
            external_id = _event_id("whatsapp", "export", item["sender"], body, received)
            if self.store.message_exists("whatsapp", external_id):
                continue
            message = self.store.upsert_message(
                {
                    "source": "whatsapp",
                    "external_id": external_id,
                    "thread_id": f"export:{filename}",
                    "sender": item["sender"],
                    "sender_name": item["sender"],
                    "subject": f"WhatsApp: {item['sender']}",
                    "snippet": body[:500],
                    "body": body,
                    "received_at": received,
                    "labels": ["export"],
                    "unread": False,
                }
            )
            stored += 1
            # Only spend LLM calls on likely deadline/action messages.
            if re.search(
                r"\b(due|deadline|last date|submit|pay|register|exam|interview|fee|form)\b",
                body,
                re.I,
            ):
                extraction = classify_message(
                    {
                        "subject": f"WhatsApp: {item['sender']}",
                        "from_name": item["sender"],
                        "body": body,
                        "received_at": received,
                    },
                    self.llm,
                    now=datetime.now().astimezone(),
                    timezone_name=self.settings.timezone,
                )
                if extraction.is_deadline and extraction.deadline:
                    self.store.create_deadline(
                        source="whatsapp",
                        source_id=external_id,
                        title=extraction.deadline["title"],
                        due_date=extraction.deadline["due_date"],
                        due_at=extraction.deadline.get("due_at") or None,
                        category=extraction.category,
                        priority=extraction.priority,
                        confidence=float(extraction.deadline.get("confidence", 0.55)),
                        evidence=extraction.deadline.get("evidence", ""),
                        timezone_name=self.settings.timezone,
                    )
                    deadlines += 1
                self.store.upsert_message(
                    {
                        "source": "whatsapp",
                        "external_id": external_id,
                        "thread_id": message.thread_id,
                        "sender": item["sender"],
                        "sender_name": item["sender"],
                        "subject": f"WhatsApp: {item['sender']}",
                        "snippet": body[:500],
                        "body": body,
                        "received_at": received,
                        "labels": ["export"],
                        "category": extraction.category,
                        "priority": extraction.priority,
                        "summary": extraction.summary,
                        "needs_action": extraction.needs_action,
                        "flags": extraction.flags,
                        "unread": False,
                    }
                )
        self.audit.log(
            "companion.import",
            tool="whatsapp.export",
            detail={"filename": filename, "stored": stored, "deadlines": deadlines},
        )
        return {
            "ok": True,
            "stored": stored,
            "deadlines": deadlines,
            "parsed": len(parsed),
        }


def _is_whatsapp(package: str, app: str) -> bool:
    value = f"{package} {app}".lower()
    return "whatsapp" in value or package in WHATSAPP_PACKAGES


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _event_id(source: str, package: str, title: str, text: str, received: str) -> str:
    raw = f"{source}|{package}|{title}|{text}|{received[:16]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _received_at(value: Any) -> str:
    if value:
        try:
            if isinstance(value, (int, float)):
                # Android timestamps are milliseconds.
                return datetime.fromtimestamp(float(value) / (1000 if value > 1e12 else 1)).astimezone().isoformat()
            return datetime.fromisoformat(str(value)).astimezone().isoformat()
        except Exception:
            pass
    return datetime.now().astimezone().isoformat()


def _parse_export_datetime(date_raw: str, time_raw: str) -> str:
    cleaned = re.sub(r"\s+", " ", f"{date_raw} {time_raw}".replace("-", "/")).strip()
    formats = (
        "%d/%m/%y %I:%M %p",
        "%d/%m/%Y %I:%M %p",
        "%m/%d/%y %I:%M %p",
        "%m/%d/%Y %I:%M %p",
        "%d/%m/%y %H:%M",
        "%d/%m/%Y %H:%M",
        "%d/%m/%y %I:%M:%S %p",
        "%d/%m/%Y %I:%M:%S %p",
    )
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).astimezone().isoformat()
        except ValueError:
            continue
    return datetime.now().astimezone().isoformat()
