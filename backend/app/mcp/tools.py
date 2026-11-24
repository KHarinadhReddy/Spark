from __future__ import annotations

from typing import Any

from .registry import Registry, Tool


def build_registry(workspace: Any) -> Registry:
    """Wire the MCP-style tools to whichever workspace provider is active."""

    registry = Registry()

    # ------------------------------------------------------------- calendar
    registry.register(
        Tool(
            name="calendar.list_events",
            description="List calendar events in a time range. Read-only.",
            risk="read",
            input_schema={
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "ISO start (inclusive)"},
                    "end": {"type": "string", "description": "ISO end (inclusive)"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
            handler=lambda start=None, end=None, limit=20: workspace.list_events(
                start=start, end=end, limit=limit
            ),
        )
    )
    registry.register(
        Tool(
            name="calendar.create_event",
            description="Create a calendar event. Requires user approval.",
            risk="write",
            input_schema={
                "type": "object",
                "required": ["summary", "start", "end"],
                "properties": {
                    "summary": {"type": "string"},
                    "start": {"type": "string", "description": "ISO datetime with offset"},
                    "end": {"type": "string", "description": "ISO datetime with offset"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                },
            },
            handler=lambda **kwargs: workspace.create_event(**kwargs),
            undo_handler=lambda data: workspace.delete_event(data["event_id"]),
            undo_builder=lambda result: {"event_id": result["event"]["id"]},
        )
    )

    # ---------------------------------------------------------------- gmail
    registry.register(
        Tool(
            name="gmail.search_emails",
            description="Search the student's inbox. Read-only.",
            risk="read",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
            },
            handler=lambda query="", limit=10: workspace.search_emails(query=query, limit=limit),
        )
    )
    registry.register(
        Tool(
            name="gmail.read_email",
            description="Read one email by id. Read-only.",
            risk="read",
            input_schema={
                "type": "object",
                "required": ["email_id"],
                "properties": {"email_id": {"type": "string"}},
            },
            handler=lambda email_id: workspace.read_email(email_id),
        )
    )
    registry.register(
        Tool(
            name="gmail.create_draft",
            description="Save an email draft (never sends). Requires user approval.",
            risk="write",
            input_schema={
                "type": "object",
                "required": ["subject", "body"],
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
            },
            handler=lambda to="", subject="", body="": workspace.create_draft(
                to=to, subject=subject, body=body
            ),
            undo_handler=lambda data: workspace.delete_draft(data["draft_id"]),
            undo_builder=lambda result: {"draft_id": result["draft"]["id"]},
        )
    )

    # ---------------------------------------------------------------- drive
    registry.register(
        Tool(
            name="drive.search_files",
            description="Search Drive files and notes. Read-only.",
            risk="read",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
            },
            handler=lambda query="", limit=10: workspace.search_files(query=query, limit=limit),
        )
    )
    registry.register(
        Tool(
            name="drive.read_file",
            description="Read a Drive file's text content. Read-only.",
            risk="read",
            input_schema={
                "type": "object",
                "required": ["file_id"],
                "properties": {"file_id": {"type": "string"}},
            },
            handler=lambda file_id: workspace.read_file(file_id),
        )
    )

    return registry
