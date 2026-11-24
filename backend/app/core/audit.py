from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .db import Database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditLog:
    """Append-only activity feed. Every read batch and write decision lands here."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def log(
        self,
        event: str,
        *,
        action_id: str | None = None,
        tool: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "id": f"aud_{uuid.uuid4().hex[:12]}",
            "ts": _now(),
            "event": event,
            "action_id": action_id,
            "tool": tool,
            "detail": detail or {},
        }
        self.db.execute(
            "INSERT INTO audit (id, ts, event, action_id, tool, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (
                entry["id"],
                entry["ts"],
                entry["event"],
                entry["action_id"],
                entry["tool"],
                json.dumps(entry["detail"], ensure_ascii=False),
            ),
        )
        return entry

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            "SELECT * FROM audit ORDER BY ts DESC LIMIT ?", (limit,)
        )
        return [
            {
                "id": row["id"],
                "ts": row["ts"],
                "event": row["event"],
                "action_id": row["action_id"],
                "tool": row["tool"],
                "detail": json.loads(row["detail"] or "{}"),
            }
            for row in rows
        ]
