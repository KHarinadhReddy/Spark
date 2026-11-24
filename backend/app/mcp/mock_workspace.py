from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..core.guardrails import scan_untrusted


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="minutes")


STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "what", "when", "where",
    "which", "who", "why", "how", "about", "into", "your", "have", "has", "are",
    "was", "were", "will", "would", "could", "should", "please", "find", "search",
    "show", "give", "tell", "any", "all", "our", "their", "there", "here", "been",
}


def _tokens(query: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) > 2 and token not in STOPWORDS
    ]


class MockWorkspace:
    """Deterministic, realistic student workspace used for the hackathon demo.

    State is persisted to a JSON file so approvals and undos survive a restart.
    """

    def __init__(self, state_path: Path, seed_path: Path) -> None:
        self.state_path = Path(state_path)
        self.seed_path = Path(seed_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            self.state_path.write_text(
                self.seed_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
        self._state = json.loads(self.state_path.read_text(encoding="utf-8"))

    # ---------------------------------------------------------------- storage
    def _save(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    @property
    def profile(self) -> dict[str, Any]:
        return self._state.get("profile", {})

    # ------------------------------------------------------------ calendar API
    def list_events(self, start: str | None = None, end: str | None = None, limit: int = 20) -> dict[str, Any]:
        events = self._state.get("events", [])
        if start:
            events = [event for event in events if event["end"] >= start]
        if end:
            events = [event for event in events if event["start"] <= end]
        events = sorted(events, key=lambda event: event["start"])[: int(limit)]
        return {"events": events, "count": len(events)}

    def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
    ) -> dict[str, Any]:
        event = {
            "id": f"evt_{uuid.uuid4().hex[:10]}",
            "summary": summary,
            "description": description,
            "location": location,
            "start": start,
            "end": end,
            "status": "confirmed",
            "html_link": "",
            "provider": "demo",
        }
        self._state.setdefault("events", []).append(event)
        self._save()
        return {"event": event}

    def delete_event(self, event_id: str) -> dict[str, Any]:
        before = len(self._state.get("events", []))
        self._state["events"] = [
            event for event in self._state.get("events", []) if event["id"] != event_id
        ]
        removed = before - len(self._state["events"])
        if removed:
            self._save()
        return {"deleted": bool(removed), "event_id": event_id}

    # --------------------------------------------------------------- gmail API
    def search_emails(self, query: str = "", limit: int = 10) -> dict[str, Any]:
        words = _tokens(query)
        scored: list[tuple[int, dict[str, Any]]] = []
        for email in self._state.get("emails", []):
            haystack = " ".join(
                [
                    email.get("subject", ""),
                    email.get("from", ""),
                    email.get("from_name", ""),
                    " ".join(email.get("labels", [])),
                    email.get("body", ""),
                ]
            ).lower()
            score = sum(
                (3 if word in email.get("subject", "").lower() else 1)
                + (2 if word in email.get("from", "").lower() else 0)
                for word in words
                if word in haystack
            )
            if not words or score:
                scored.append((score or 1, email))
        scored.sort(key=lambda pair: (pair[0], pair[1].get("date", "")), reverse=True)
        selected = [email for _, email in scored[: int(limit)]]
        return {
            "emails": [self._email_summary(email) for email in selected],
            "count": len(selected),
        }

    def read_email(self, email_id: str) -> dict[str, Any]:
        for email in self._state.get("emails", []):
            if email["id"] == email_id:
                flags = scan_untrusted(email.get("body", ""))
                return {
                    **self._email_summary(email),
                    "body": email.get("body", ""),
                    "flags": [flag.as_dict() for flag in flags],
                }
        raise KeyError(f"email not found: {email_id}")

    def _email_summary(self, email: dict[str, Any]) -> dict[str, Any]:
        body = email.get("body", "")
        flags = scan_untrusted(body)
        return {
            "id": email["id"],
            "thread_id": email.get("thread_id", email["id"]),
            "from": email.get("from", ""),
            "from_name": email.get("from_name", ""),
            "to": email.get("to", "me"),
            "subject": email.get("subject", ""),
            "date": email.get("date", ""),
            "snippet": re.sub(r"\s+", " ", body)[:180],
            "labels": email.get("labels", []),
            "unread": email.get("unread", False),
            "flags": [flag.as_dict() for flag in flags],
        }

    def create_draft(self, to: str, subject: str, body: str) -> dict[str, Any]:
        draft = {
            "id": f"draft_{uuid.uuid4().hex[:10]}",
            "to": to,
            "subject": subject,
            "body": body,
            "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
            "provider": "demo",
        }
        self._state.setdefault("drafts", []).append(draft)
        self._save()
        return {"draft": draft}

    def delete_draft(self, draft_id: str) -> dict[str, Any]:
        before = len(self._state.get("drafts", []))
        self._state["drafts"] = [
            draft for draft in self._state.get("drafts", []) if draft["id"] != draft_id
        ]
        removed = before - len(self._state["drafts"])
        if removed:
            self._save()
        return {"deleted": bool(removed), "draft_id": draft_id}

    # --------------------------------------------------------------- drive API
    def search_files(self, query: str = "", limit: int = 10) -> dict[str, Any]:
        words = _tokens(query)
        files = []
        for file in self._state.get("files", []):
            haystack = f"{file.get('name', '')} {file.get('content', '')}".lower()
            if not words or any(word in haystack for word in words):
                files.append(file)
        return {"files": files[: int(limit)], "count": len(files[: int(limit)])}

    def read_file(self, file_id: str) -> dict[str, Any]:
        for file in self._state.get("files", []):
            if file["id"] == file_id:
                flags = scan_untrusted(file.get("content", ""))
                return {**file, "flags": [flag.as_dict() for flag in flags]}
        raise KeyError(f"file not found: {file_id}")

    # ------------------------------------------------------------------ helper
    def events_between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return self.list_events(start=_iso(start), end=_iso(end))["events"]

    def upcoming_events(self, now: datetime, days: int = 7) -> list[dict[str, Any]]:
        return self.events_between(now, now + timedelta(days=days))
