from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..mcp.registry import PermissionDenied, Registry, ToolError
from .audit import AuditLog
from .db import Database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ActionError(Exception):
    pass


class ActionNotFound(ActionError):
    pass


class ActionStateError(ActionError):
    pass


class ActionExecutionError(ActionError):
    pass


@dataclass(slots=True)
class Action:
    id: str
    tool: str
    args: dict[str, Any]
    args_hash: str
    preview: dict[str, Any]
    status: str
    source: str | None
    created_at: str
    decided_at: str | None = None
    executed_at: str | None = None
    result: dict[str, Any] | None = None
    undo: dict[str, Any] | None = None
    undo_status: str | None = None

    @property
    def undoable(self) -> bool:
        return self.status == "executed" and self.undo_status == "available"

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "args": self.args,
            "preview": self.preview,
            "status": self.status,
            "source": self.source,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
            "executed_at": self.executed_at,
            "result": self.result,
            "undoable": self.undoable,
            "undo_status": self.undo_status,
        }


def _args_hash(args: dict[str, Any]) -> str:
    canonical = json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ApprovalGate:
    """The only path from a plan to a side effect.

    A write is stored as ``pending`` first and executes only when a human approves
    that exact action id. Arguments are hashed at proposal time and re-checked at
    approval time, so an agent (or a compromised client) cannot swap the payload
    after the user has seen the preview.
    """

    def __init__(self, db: Database, registry: Registry, audit: AuditLog) -> None:
        self.db = db
        self.registry = registry
        self.audit = audit

    # ------------------------------------------------------------ lifecycle
    def propose(
        self,
        tool: str,
        args: dict[str, Any],
        preview: dict[str, Any],
        source: str = "agent",
    ) -> Action:
        registered = self.registry.get(tool)
        if registered.risk != "write":
            raise ActionStateError(f"{tool} is read-only and does not need approval")

        digest = _args_hash(args)
        existing = self.db.query_one(
            "SELECT * FROM actions WHERE tool = ? AND args_hash = ? AND status = 'pending' ORDER BY created_at LIMIT 1",
            (tool, digest),
        )
        if existing:
            return self._from_row(existing)

        action = Action(
            id=f"act_{uuid.uuid4().hex[:12]}",
            tool=tool,
            args=args,
            args_hash=digest,
            preview=preview,
            status="pending",
            source=source,
            created_at=_now(),
        )
        self.db.execute(
            """INSERT INTO actions
               (id, tool, args, args_hash, preview, status, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                action.id,
                action.tool,
                json.dumps(action.args, ensure_ascii=False),
                action.args_hash,
                json.dumps(action.preview, ensure_ascii=False),
                action.status,
                action.source,
                action.created_at,
            ),
        )
        self.audit.log(
            "action.proposed",
            action_id=action.id,
            tool=tool,
            detail={"title": preview.get("title", tool), "source": source},
        )
        return action

    def approve(self, action_id: str) -> Action:
        action = self.get(action_id)
        if action.status != "pending":
            raise ActionStateError(f"action is {action.status}, not pending")
        if _args_hash(action.args) != action.args_hash:
            self.audit.log(
                "action.tampered",
                action_id=action.id,
                tool=action.tool,
                detail={"reason": "arguments changed after preview"},
            )
            raise ActionStateError("action payload changed after preview; re-plan required")

        decided_at = _now()
        try:
            result = self.registry.execute_write(
                action.tool, action.args, approval_id=action.id
            )
        except (PermissionDenied, ToolError) as exc:
            self._fail(action, str(exc), decided_at)
            raise ActionExecutionError(str(exc)) from exc
        except Exception as exc:  # provider errors must leave a trail
            self._fail(action, str(exc), decided_at)
            raise ActionExecutionError(f"{action.tool} failed: {exc}") from exc

        undo_data = None
        tool = self.registry.get(action.tool)
        if tool.undo_builder:
            undo_data = tool.undo_builder(result)

        self.db.execute(
            """UPDATE actions SET status = 'executed', decided_at = ?, executed_at = ?,
               result = ?, undo = ?, undo_status = ? WHERE id = ?""",
            (
                decided_at,
                _now(),
                json.dumps(result, ensure_ascii=False),
                json.dumps(undo_data, ensure_ascii=False) if undo_data else None,
                "available" if undo_data else "unavailable",
                action.id,
            ),
        )
        self.audit.log(
            "action.executed",
            action_id=action.id,
            tool=action.tool,
            detail={"title": action.preview.get("title", action.tool), "result": result},
        )
        return self.get(action.id)

    def reject(self, action_id: str) -> Action:
        action = self.get(action_id)
        if action.status != "pending":
            raise ActionStateError(f"action is {action.status}, not pending")
        self.db.execute(
            "UPDATE actions SET status = 'rejected', decided_at = ? WHERE id = ?",
            (_now(), action.id),
        )
        self.audit.log(
            "action.rejected",
            action_id=action.id,
            tool=action.tool,
            detail={"title": action.preview.get("title", action.tool)},
        )
        return self.get(action.id)

    def undo(self, action_id: str) -> Action:
        action = self.get(action_id)
        if action.status != "executed" or action.undo_status != "available" or not action.undo:
            raise ActionStateError("this action has nothing to undo")
        try:
            self.registry.undo(action.tool, action.undo)
        except Exception as exc:
            self.db.execute(
                "UPDATE actions SET undo_status = 'failed' WHERE id = ?", (action.id,)
            )
            self.audit.log(
                "action.undo_failed",
                action_id=action.id,
                tool=action.tool,
                detail={"error": str(exc)},
            )
            raise ActionExecutionError(f"undo failed: {exc}") from exc
        self.db.execute(
            "UPDATE actions SET undo_status = 'undone' WHERE id = ?", (action.id,)
        )
        self.audit.log(
            "action.undone",
            action_id=action.id,
            tool=action.tool,
            detail={"title": action.preview.get("title", action.tool)},
        )
        return self.get(action.id)

    # -------------------------------------------------------------- queries
    def get(self, action_id: str) -> Action:
        row = self.db.query_one("SELECT * FROM actions WHERE id = ?", (action_id,))
        if not row:
            raise ActionNotFound(f"action not found: {action_id}")
        return self._from_row(row)

    def pending(self) -> list[Action]:
        rows = self.db.query_all(
            "SELECT * FROM actions WHERE status = 'pending' ORDER BY created_at DESC"
        )
        return [self._from_row(row) for row in rows]

    def recent(self, limit: int = 30) -> list[Action]:
        rows = self.db.query_all(
            "SELECT * FROM actions ORDER BY created_at DESC LIMIT ?", (int(limit),)
        )
        return [self._from_row(row) for row in rows]

    def expire_pending(self, reason: str) -> int:
        """Cancel staged writes when the data source changes (demo <-> live Google)."""
        pending = self.pending()
        if not pending:
            return 0
        self.db.execute(
            "UPDATE actions SET status = 'rejected', decided_at = ?, result = ? WHERE status = 'pending'",
            (_now(), json.dumps({"expired": reason})),
        )
        self.audit.log(
            "actions.expired",
            detail={"reason": reason, "count": len(pending)},
        )
        return len(pending)

    # -------------------------------------------------------------- internal
    def _fail(self, action: Action, message: str, decided_at: str) -> None:
        self.db.execute(
            """UPDATE actions SET status = 'failed', decided_at = ?, result = ?
               WHERE id = ?""",
            (decided_at, json.dumps({"error": message}), action.id),
        )
        self.audit.log(
            "action.failed",
            action_id=action.id,
            tool=action.tool,
            detail={"error": message},
        )

    @staticmethod
    def _from_row(row: Any) -> Action:
        return Action(
            id=row["id"],
            tool=row["tool"],
            args=json.loads(row["args"]),
            args_hash=row["args_hash"],
            preview=json.loads(row["preview"]),
            status=row["status"],
            source=row["source"],
            created_at=row["created_at"],
            decided_at=row["decided_at"],
            executed_at=row["executed_at"],
            result=json.loads(row["result"]) if row["result"] else None,
            undo=json.loads(row["undo"]) if row["undo"] else None,
            undo_status=row["undo_status"],
        )
