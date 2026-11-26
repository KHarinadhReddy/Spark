from __future__ import annotations

import json
import logging
import secrets
import threading
import uuid
from datetime import datetime, time
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from .agent.brain import SparkBrain
from .agent.companion import CompanionService
from .agent.deadlines import find_deadlines, format_date, plus_minutes
from .agent.gmail_sync import GmailSync
from .agent.llm_client import LLMClient
from .agent.reminders import ReminderService
from .agent.scheduler import BackgroundWorker
from .agent.spark import SparkAgent, _pick, _short_title
from .config import Settings
from .core.approval import (
    Action,
    ActionExecutionError,
    ActionNotFound,
    ActionStateError,
    ApprovalGate,
)
from .core.audit import AuditLog
from .core.db import Database
from .core.store import UnifiedStore
from .forms import FormService
from .mcp.google_workspace import GoogleAuthError, GoogleTokenStore, GoogleWorkspace
from .mcp.mock_workspace import MockWorkspace
from .mcp.tools import build_registry
from .voice import ElevenLabsVoice, VoiceError, VoiceNotConfigured, VoiceService

Language = Literal["en", "hi"]

log = logging.getLogger("spark.api")


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    language: Language | None = None


class TtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=2500)
    language: Language = "en"


class DeadlineAddIn(BaseModel):
    language: Language = "en"


class SnoozeIn(BaseModel):
    days: int = Field(default=1, ge=1, le=30)


class CompanionPairIn(BaseModel):
    name: str = Field(default="Android phone", max_length=80)
    platform: str = Field(default="android", max_length=40)


class CompanionNotificationIn(BaseModel):
    app: str = ""
    package: str = ""
    title: str = ""
    text: str = ""
    body: str = ""
    big_text: str = ""
    subtext: str = ""
    timestamp: int | float | str | None = None
    chat: str = ""


class CompanionImportIn(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    filename: str = Field(default="whatsapp.txt", max_length=120)


class FormFieldIn(BaseModel):
    name: str = ""
    id: str = ""
    label: str = ""
    aria_label: str = ""
    placeholder: str = ""
    type: str = "text"
    required: bool = False
    options: list[str] = Field(default_factory=list)
    selector: str = ""


class FormAnalyzeIn(BaseModel):
    url: str = ""
    title: str = ""
    fields: list[FormFieldIn] = Field(default_factory=list)


class FormSubmitIn(BaseModel):
    url: str = ""
    title: str = ""
    field_count: int = 0
    approved: bool = False
    detail: dict[str, Any] = Field(default_factory=dict)


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.ensure_dirs()
        self.db = Database(settings.db_path)
        self.db.init()
        self.audit = AuditLog(self.db)
        self.store = UnifiedStore(self.db, settings.timezone)
        self.store.ensure_defaults()
        self.llm = LLMClient(settings)
        self.voice = ElevenLabsVoice(settings)
        self.voice_service = VoiceService(settings)
        self.mock = MockWorkspace(settings.mock_state_path, settings.seed_path)
        self.tokens = GoogleTokenStore(
            settings.google_token_path,
            settings.google_client_id,
            settings.google_client_secret,
            settings.google_redirect_uri,
        )
        self.workspace: Any = self.mock
        self._wire_workspace()
        self.gmail_sync = GmailSync(
            settings, self.store, self.audit, self.llm, lambda: self.workspace
        )
        self.reminders = ReminderService(self.store, self.audit)
        self.companion = CompanionService(settings, self.store, self.llm, self.audit)
        self.forms = FormService(settings, self.store, self.llm, self.audit)
        self.worker = BackgroundWorker(
            self.gmail_sync,
            self.reminders,
            self.store,
            interval_minutes=settings.sync_interval_minutes,
            retention_days=settings.retention_days,
        )
        if self.tokens.connected:
            self._activate_google()

    def _wire_workspace(self) -> None:
        self.registry = build_registry(self.workspace)
        self.gate = ApprovalGate(self.db, self.registry, self.audit)
        self.agent = SparkAgent(
            self.settings,
            self.registry,
            self.gate,
            self.workspace,
            self.audit,
            store=self.store,
        )
        self.brain = SparkBrain(
            self.settings,
            self.registry,
            self.gate,
            self.workspace,
            self.audit,
            self.store,
            self.llm,
            self.agent,
        )

    def _activate_google(self) -> None:
        self.gate.expire_pending("switched to live Google workspace")
        self.workspace = GoogleWorkspace(self.tokens, self.settings.timezone)
        self._wire_workspace()

    def refresh_workspace(self) -> None:
        if self.tokens.connected:
            self._activate_google()
        else:
            self.gate.expire_pending("switched to demo workspace")
            self.workspace = self.mock
            self._wire_workspace()

    def start_worker(self) -> None:
        if self.settings.background_sync:
            self.worker.start()

    def stop_worker(self) -> None:
        self.worker.stop()

    def add_deadline_to_calendar(self, deadline_id: str, language: str) -> tuple[dict[str, Any], str]:
        if deadline_id.startswith("dl_"):
            deadline = self.store.get_deadline(deadline_id)
            if deadline.due_at:
                start = datetime.fromisoformat(deadline.due_at)
            else:
                start = datetime.combine(
                    deadline.due_date_value or datetime.now().date(), time(9, 0)
                )
            end = plus_minutes(start, 30)
            title = deadline.title
            description = (
                f"Detected in {deadline.source} ({deadline.source_id}).\n\n"
                f"{deadline.evidence}\n\nAdded by Spark after student approval."
            )
            preview = {
                "title": f"Add “{_short_title(title)}” to Calendar",
                "summary": f"{format_date(start.date(), language)} · "
                f"{start.strftime('%I:%M %p').lstrip('0')}–{end.strftime('%I:%M %p').lstrip('0')}",
                "fields": [
                    {"label": "Event", "value": f"Deadline: {_short_title(title)}"},
                    {"label": "Date", "value": format_date(start.date(), language)},
                    {"label": "Source", "value": f"{deadline.source} · {deadline.source_id}"},
                ],
                "note": _pick(
                    language,
                    "This is a reminder event. It will be created only after you approve.",
                    "यह रिमाइंडर इवेंट है। स्वीकृति के बाद ही बनेगा।",
                ),
                "undo_hint": "You can undo this from Activity.",
            }
            action = self.gate.propose(
                "calendar.create_event",
                {
                    "summary": f"Deadline: {_short_title(title)}",
                    "start": start.isoformat(timespec="minutes"),
                    "end": end.isoformat(timespec="minutes"),
                    "description": description,
                },
                preview,
                source=f"deadline:{deadline_id}",
            )
            reply = _pick(
                language,
                f"Card ready: “{_short_title(title)}” on {format_date(start.date(), language)}. "
                "Nothing is on your calendar until you approve.",
                f"कार्ड तैयार है: “{_short_title(title)}”, {format_date(start.date(), 'hi')}। "
                "आपकी मंज़ूरी तक कैलेंडर में कुछ नहीं जुड़ेगा।",
            )
            return action.public(), reply
        action, reply = self.agent.add_deadline_to_calendar(deadline_id, language)
        return action, reply


def _decision_message(action: Action, decision: str) -> tuple[str, str]:
    title = action.preview.get("title", action.tool)
    if decision == "approved":
        return (
            f"Approved — “{title}” is done. The action is in your activity log and can be undone.",
            f"स्वीकृत — “{title}” पूरा हुआ। यह गतिविधि लॉग में है और इसे पूर्ववत किया जा सकता है।",
        )
    if decision == "rejected":
        return (
            f"Dismissed — “{title}” was not executed. No changes were made.",
            f"खारिज — “{title}” लागू नहीं हुआ। कोई बदलाव नहीं हुआ।",
        )
    return (
        f"Undone — “{title}” was reversed and removed.",
        f"पूर्ववत — “{title}” को हटा दिया गया।",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    container = Container(settings)

    app = FastAPI(
        title="Spark",
        version="2.0.0",
        description=(
            "Voice-first personal assistant for students. Real Gmail/Calendar/Drive, "
            "unified WhatsApp notifications, deadline radar, natural voice, and an "
            "approval gate around every write."
        ),
    )
    app.state.ctx = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_origin_regex=(
            r"http://(localhost|127\.0\.0\.1):\d+"
            r"|chrome-extension://[a-p]{32}"
        ),
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    if settings.public_base_url and not settings.owner_token:
        log.warning(
            "SPARK_OWNER_TOKEN is empty on a public deployment (%s). "
            "Every API route is readable by anyone who finds the URL.",
            settings.public_base_url,
        )

    @app.middleware("http")
    async def owner_auth(request: Request, call_next):
        if not settings.owner_token:
            return await call_next(request)
        # CORS preflights never carry credentials.
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        exempt = (
            path == "/api/health"
            or path == "/api/auth/google/callback"
            or path in {
                "/api/companion/notifications",
                "/api/companion/import",
                "/api/companion/me",
            }
            or not path.startswith("/api/")
        )
        if exempt:
            return await call_next(request)
        token = request.headers.get("x-spark-token") or ""
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
        if not secrets.compare_digest(token, settings.owner_token):
            return JSONResponse(
                status_code=401,
                content={"detail": "Spark is locked. Add your owner token in Settings."},
            )
        return await call_next(request)

    @app.on_event("startup")
    def _startup() -> None:
        container.start_worker()

    @app.on_event("shutdown")
    def _shutdown() -> None:
        container.stop_worker()

    # ----------------------------------------------------------------- health
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "app": "Spark",
            "mode": settings.mode,
            "capabilities": settings.capabilities(),
            "pending_actions": len(container.gate.pending()),
            "inbox": container.store.stats(),
            "sync": container.gmail_sync.status(),
            "voice": container.voice_service.status(),
            "llm": container.llm.status(),
            "worker": {"running": container.worker.running},
        }

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return {
            "app": "Spark",
            "version": "2.0.0",
            "tagline": "Reads freely. Writes only after you approve.",
            "mode": settings.mode,
            "demo_enabled": settings.demo_enabled,
            "capabilities": settings.capabilities(),
            "profile": container.store.get_profile() or container.agent.profile,
            "google": {
                "configured": settings.google_configured,
                "connected": settings.google_connected,
                "start_url": "/api/auth/google/start",
            },
            "llm": container.llm.status(),
            "voice": container.voice_service.status(),
            "sync": container.gmail_sync.status(),
            "integrations": {
                "gmail": "google" if settings.google_connected else "demo",
                "calendar": "google" if settings.google_connected else "demo",
                "drive": "google" if settings.google_connected else "demo",
                "whatsapp": "companion",
                "forms": "extension",
                "reminders": "in-app",
            },
            "prompts": [
                "Give me my morning brief",
                "What deadlines am I missing?",
                "What's due this week?",
                "What's on my calendar today?",
                "Summarize my important messages",
                "Draft a reminder to the accounts office about the fee",
                "Add a study block on 29 Nov at 3 PM",
                "Find my wHACKiest checklist",
            ],
            "tools": container.registry.catalog(),
        }

    @app.get("/api/tools")
    def tools() -> dict[str, Any]:
        return {"tools": container.registry.catalog()}

    # ------------------------------------------------------------------ agent
    @app.post("/api/chat")
    def chat(payload: ChatIn) -> dict[str, Any]:
        try:
            result = container.brain.handle(payload.message, payload.language)
            return result.public()
        except Exception as exc:
            container.audit.log("agent.error", detail={"error": str(exc)[:300]})
            raise HTTPException(
                status_code=500,
                detail="Spark hit a snag handling that request. Please try again.",
            ) from exc

    @app.post("/api/chat/stream")
    async def chat_stream(payload: ChatIn) -> StreamingResponse:
        """SSE stream of the assistant reply — first token arrives fast."""

        def event_stream():
            reply_iter = container.brain.stream_reply(payload.message, payload.language)
            final_reply = ""
            for chunk in reply_iter:
                final_reply = chunk
                yield f"event: delta\ndata: {json.dumps({'text': chunk})}\n\n"
            yield f"event: done\ndata: {json.dumps({'reply': final_reply})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/api/brief")
    def brief(language: Language = "en") -> dict[str, Any]:
        return container.agent.brief(language)

    @app.get("/api/deadlines")
    def deadlines(language: Language = "en", status: str = "active") -> dict[str, Any]:
        stored = container.store.list_deadlines(status=status, limit=100)
        if stored:
            items = [deadline.public() for deadline in stored]
        elif status in {"active", "all"}:
            from .agent.deadlines import find_deadlines as legacy_find

            found = legacy_find(container.workspace, container.agent.now())
            items = [deadline.public() for deadline in found]
        else:
            items = []
        return {
            "language": language,
            "count": len(items),
            "deadlines": items,
            "pending_cards": [action.public() for action in container.gate.pending()],
        }

    @app.post("/api/deadlines/{deadline_id}/add")
    def add_deadline(
        deadline_id: str, payload: DeadlineAddIn | None = None
    ) -> dict[str, Any]:
        language = payload.language if payload else "en"
        try:
            action, reply = container.add_deadline_to_calendar(deadline_id, language)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="No upcoming deadline for that message") from exc
        return {"action": action, "reply": reply, "language": language}

    @app.post("/api/deadlines/{deadline_id}/complete")
    def complete_deadline(deadline_id: str) -> dict[str, Any]:
        try:
            deadline = container.store.update_deadline_status(deadline_id, "completed")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Deadline not found") from exc
        container.audit.log("deadline.completed", tool="deadlines", detail={"id": deadline_id})
        return {"deadline": deadline.public()}

    @app.post("/api/deadlines/{deadline_id}/dismiss")
    def dismiss_deadline(deadline_id: str) -> dict[str, Any]:
        try:
            deadline = container.store.update_deadline_status(deadline_id, "dismissed")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Deadline not found") from exc
        container.audit.log("deadline.dismissed", tool="deadlines", detail={"id": deadline_id})
        return {"deadline": deadline.public()}

    @app.post("/api/deadlines/{deadline_id}/snooze")
    def snooze_deadline(deadline_id: str, payload: SnoozeIn | None = None) -> dict[str, Any]:
        days = payload.days if payload else 1
        try:
            deadline = container.store.snooze_deadline(deadline_id, days)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Deadline not found") from exc
        container.audit.log("deadline.snoozed", tool="deadlines", detail={"id": deadline_id, "days": days})
        return {"deadline": deadline.public()}

    # -------------------------------------------------------- approval + undo
    @app.get("/api/actions")
    def actions(limit: int = 30) -> dict[str, Any]:
        return {
            "pending": [action.public() for action in container.gate.pending()],
            "recent": [action.public() for action in container.gate.recent(limit)],
        }

    @app.get("/api/actions/{action_id}")
    def action_detail(action_id: str) -> dict[str, Any]:
        try:
            return container.gate.get(action_id).public()
        except ActionNotFound as exc:
            raise HTTPException(status_code=404, detail="Action not found") from exc

    def _handle_action(action_id: str, decision: str) -> dict[str, Any]:
        try:
            if decision == "approve":
                action = container.gate.approve(action_id)
            elif decision == "reject":
                action = container.gate.reject(action_id)
            else:
                action = container.gate.undo(action_id)
        except ActionNotFound as exc:
            raise HTTPException(status_code=404, detail="Action not found") from exc
        except ActionStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ActionExecutionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        english, hindi = _decision_message(action, decision)
        return {
            "action": action.public(),
            "message": english,
            "message_hi": hindi,
            "pending": [item.public() for item in container.gate.pending()],
        }

    @app.post("/api/actions/{action_id}/approve")
    def approve(action_id: str) -> dict[str, Any]:
        return _handle_action(action_id, "approve")

    @app.post("/api/actions/{action_id}/reject")
    def reject(action_id: str) -> dict[str, Any]:
        return _handle_action(action_id, "reject")

    @app.post("/api/actions/{action_id}/undo")
    def undo(action_id: str) -> dict[str, Any]:
        return _handle_action(action_id, "undo")

    @app.get("/api/audit")
    def audit(limit: int = 100) -> dict[str, Any]:
        return {"audit": container.audit.list(limit=min(max(limit, 1), 200))}

    # ------------------------------------------------------------------ inbox
    @app.get("/api/inbox")
    def inbox(
        source: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        unread: bool | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        messages = container.store.list_messages(
            source=source,
            category=category,
            priority=priority,
            unread=unread,
            query=query,
            limit=min(max(limit, 1), 200),
            offset=max(offset, 0),
        )
        return {
            "messages": [message.public() for message in messages],
            "stats": container.store.inbox_stats(),
            "sources": ["gmail", "whatsapp", "notification"],
        }

    @app.get("/api/messages/{message_id}")
    def message_detail(message_id: str, mark_read: bool = False) -> dict[str, Any]:
        try:
            message = container.store.get_message(message_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Message not found") from exc
        if mark_read:
            container.store.mark_message_read(message_id)
        return message.public(include_body=True)

    @app.post("/api/messages/{message_id}/read")
    def mark_read(message_id: str) -> dict[str, Any]:
        container.store.mark_message_read(message_id)
        return {"ok": True, "stats": container.store.inbox_stats()}

    # ----------------------------------------------------------- notifications
    @app.get("/api/notifications")
    def notifications(limit: int = 50, unread_only: bool = False) -> dict[str, Any]:
        items = container.store.list_notifications(
            limit=min(max(limit, 1), 200), unread_only=unread_only
        )
        return {
            "notifications": [item.public() for item in items],
            "unread": container.store.unread_notifications(),
        }

    @app.get("/api/notifications/count")
    def notification_count() -> dict[str, Any]:
        return {"unread": container.store.unread_notifications()}

    @app.post("/api/notifications/{notification_id}/read")
    def read_notification(notification_id: str) -> dict[str, Any]:
        container.store.mark_notification_read(notification_id)
        return {"ok": True, "unread": container.store.unread_notifications()}

    @app.post("/api/notifications/read-all")
    def read_all_notifications() -> dict[str, Any]:
        container.store.mark_all_notifications_read()
        return {"ok": True, "unread": 0}

    # ------------------------------------------------------------ sync/reminders
    @app.post("/api/sync")
    def sync(force_initial: bool = False, limit: int = 60) -> dict[str, Any]:
        return container.gmail_sync.sync(limit=min(max(limit, 1), 200), force_initial=force_initial)

    @app.get("/api/sync/status")
    def sync_status() -> dict[str, Any]:
        return {
            **container.gmail_sync.status(),
            "worker": {"running": container.worker.running, "cycle": container.worker.cycle},
            "mode": settings.mode,
        }

    @app.post("/api/reminders/run")
    def run_reminders() -> dict[str, Any]:
        return container.reminders.run()

    @app.get("/api/reminders")
    def reminders(limit: int = 50) -> dict[str, Any]:
        rows = container.store.db.query_all(
            "SELECT * FROM reminders ORDER BY fire_at DESC LIMIT ?", (min(max(limit, 1), 200),)
        )
        return {"reminders": [dict(row) for row in rows]}

    # ------------------------------------------------------------------ profile
    @app.get("/api/profile")
    def profile() -> dict[str, Any]:
        return {"profile": container.store.get_profile()}

    @app.put("/api/profile")
    def update_profile(payload: dict[str, Any]) -> dict[str, Any]:
        return {"profile": container.forms.update_profile(payload)}

    # ---------------------------------------------------------------- companion
    def _require_companion(request: Request) -> dict[str, Any]:
        token = (
            request.headers.get("x-spark-device")
            or request.headers.get("x-spark-token")
            or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        )
        device = container.companion.authenticate(token)
        if not device:
            raise HTTPException(
                status_code=401,
                detail="Pair this device first, then send its device token.",
            )
        return device

    @app.post("/api/companion/pair")
    def companion_pair(payload: CompanionPairIn | None = None) -> dict[str, Any]:
        body = payload or CompanionPairIn()
        return container.companion.pair(body.name, body.platform)

    @app.get("/api/companion/me")
    def companion_me(request: Request) -> dict[str, Any]:
        """Device-token check used by the Android companion's Test connection."""
        device = _require_companion(request)
        return {"ok": True, "device": device}

    @app.get("/api/companion/devices")
    def companion_devices() -> dict[str, Any]:
        return {"devices": container.companion.devices()}

    @app.delete("/api/companion/devices/{device_id}")
    def companion_revoke(device_id: str) -> dict[str, Any]:
        container.companion.revoke(device_id)
        return {"ok": True}

    @app.post("/api/companion/notifications")
    def companion_notification(
        payload: CompanionNotificationIn, request: Request
    ) -> dict[str, Any]:
        _require_companion(request)
        return container.companion.ingest(payload.model_dump())

    @app.post("/api/companion/import")
    def companion_import(payload: CompanionImportIn, request: Request) -> dict[str, Any]:
        _require_companion(request)
        return container.companion.import_export(payload.text, payload.filename)

    @app.post("/api/whatsapp/import")
    def whatsapp_import(payload: CompanionImportIn) -> dict[str, Any]:
        """Import a WhatsApp chat export from the web UI (owner-authenticated)."""
        return container.companion.import_export(payload.text, payload.filename)

    # -------------------------------------------------------------------- forms
    @app.post("/api/forms/analyze")
    def forms_analyze(payload: FormAnalyzeIn) -> dict[str, Any]:
        return container.forms.analyze(
            url=payload.url,
            title=payload.title,
            fields=[field.model_dump() for field in payload.fields],
        )

    @app.post("/api/forms/fill")
    def forms_fill(payload: FormAnalyzeIn) -> dict[str, Any]:
        return container.forms.analyze(
            url=payload.url,
            title=payload.title,
            fields=[field.model_dump() for field in payload.fields],
        )

    @app.post("/api/forms/submit")
    def forms_submit(payload: FormSubmitIn) -> dict[str, Any]:
        if not payload.approved:
            raise HTTPException(
                status_code=403,
                detail="Form submission requires explicit approval in the extension.",
            )
        return container.forms.log_submit(
            url=payload.url,
            title=payload.title,
            field_count=payload.field_count,
            detail=payload.detail,
        )

    @app.get("/api/forms/stats")
    def forms_stats() -> dict[str, Any]:
        return container.forms.stats()

    # --------------------------------------------------------------- google
    @app.get("/api/auth/google/status")
    def google_status() -> dict[str, Any]:
        return {
            "configured": settings.google_configured,
            "connected": container.tokens.connected,
        }

    @app.get("/api/auth/google/start")
    def google_start() -> dict[str, str]:
        if not settings.google_configured:
            raise HTTPException(
                status_code=400,
                detail="Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
            )
        state = uuid.uuid4().hex
        return {"url": container.tokens.authorize_url(state)}

    @app.get("/api/auth/google/callback")
    def google_callback(code: str | None = None, state: str | None = None, error: str | None = None) -> Response:
        if error:
            return RedirectResponse("/?google=error")
        if not code or not state or not container.tokens.check_state(state):
            raise HTTPException(status_code=400, detail="Invalid OAuth state")
        try:
            container.tokens.exchange(code)
        except GoogleAuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        container.refresh_workspace()
        container.audit.log("google.connected", detail={"mode": settings.mode})
        threading.Thread(target=container.gmail_sync.sync, daemon=True).start()
        return RedirectResponse("/?google=connected")

    @app.post("/api/auth/google/disconnect")
    def google_disconnect() -> dict[str, Any]:
        container.tokens.disconnect()
        container.refresh_workspace()
        container.audit.log("google.disconnected")
        return {"connected": False, "mode": settings.mode}

    # ------------------------------------------------------------------ voice
    @app.get("/api/voice/status")
    def voice_status() -> dict[str, Any]:
        return container.voice_service.status()

    @app.post("/api/voice/tts")
    def tts(payload: TtsIn) -> Response:
        try:
            audio, media_type = container.voice_service.tts(payload.text, payload.language)
        except VoiceNotConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except VoiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return Response(content=audio, media_type=media_type)

    @app.post("/api/voice/stt")
    async def stt(request: Request, language: str = "") -> dict[str, Any]:
        audio = await request.body()
        if not audio:
            raise HTTPException(status_code=400, detail="No audio received")
        content_type = request.headers.get("content-type", "audio/webm")
        try:
            text = container.voice_service.stt(audio, content_type, language)
        except VoiceNotConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except VoiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"text": text}

    # ----------------------------------------------------------------- static
    dist = settings.frontend_dist
    if dist.exists() and (dist / "index.html").exists():
        assets = dist / "assets"
        if assets.exists():
            from fastapi.staticfiles import StaticFiles

            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> Response:
            if path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")
            candidate = (dist / path).resolve()
            try:
                candidate.relative_to(dist.resolve())
            except ValueError:
                raise HTTPException(status_code=404, detail="Not found") from None
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        def root() -> dict[str, Any]:
            return {
                "app": "Spark API",
                "status": "running",
                "ui": "Frontend not built. Run `npm install && npm run build` in frontend/.",
                "docs": "/docs",
            }

    return app


app = create_app()
