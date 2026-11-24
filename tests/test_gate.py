from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.agent.deadlines import extract_dates, find_deadlines, parse_datetime
from app.core.approval import ActionNotFound, ActionStateError
from app.mcp.registry import PermissionDenied
from app.voice import VoiceNotConfigured

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 24, 8, 0, tzinfo=TZ)


def event_count(ctx) -> int:
    return len(ctx.workspace.list_events(start="2000-01-01T00:00", end="2100-01-01T00:00", limit=500)["events"])


def make_action(ctx, summary: str = "Test event"):
    args = {
        "summary": summary,
        "start": "2026-12-01T09:00+05:30",
        "end": "2026-12-01T09:30+05:30",
    }
    return ctx.gate.propose(
        "calendar.create_event",
        args,
        {"title": f"Add “{summary}” to Calendar", "fields": [], "summary": ""},
        source="test",
    )


# ---------------------------------------------------------------- deadlines
def test_extract_dates_supports_common_formats():
    text = "Pay by 05 Dec 2026. Also 2026-12-10 and December 15, 2026 and 12/12/2026."
    values = [hit.value.isoformat() for hit in extract_dates(text)]
    assert "2026-12-05" in values
    assert "2026-12-10" in values
    assert "2026-12-15" in values
    assert "2026-12-12" in values


def test_parse_datetime_day_month_without_year():
    moment = parse_datetime("Add a study block on 29 Nov at 3 PM", NOW)
    assert moment is not None
    assert moment.date().isoformat() == "2026-11-29"
    assert (moment.hour, moment.minute) == (15, 0)


def test_seed_deadlines_are_detected_and_sorted(ctx):
    found = find_deadlines(ctx.workspace, NOW)
    ids = {deadline.email_id for deadline in found}
    assert ids == {
        "em_fee_2026",
        "em_exam_form",
        "em_scholarship",
        "em_mess_fee",
        "em_library",
        "em_tcs_drive",
    }
    assert [d.when for d in found] == sorted(d.when for d in found)
    assert found[0].when.isoformat() == "2026-11-28"
    # event-only and interview emails are not deadlines
    assert "em_hackathon" not in ids
    assert "em_interview" not in ids


# ------------------------------------------------------------ approval gate
def test_proposal_does_not_execute_and_blocks_direct_write(ctx):
    before = event_count(ctx)
    action = make_action(ctx)
    assert action.status == "pending"
    assert event_count(ctx) == before

    with pytest.raises(PermissionDenied):
        ctx.registry.read(
            "calendar.create_event",
            summary="Sneaky",
            start="2026-12-01T09:00+05:30",
            end="2026-12-01T09:30+05:30",
        )
    assert event_count(ctx) == before


def test_approve_executes_and_undo_reverses(ctx):
    action = make_action(ctx)
    approved = ctx.gate.approve(action.id)
    assert approved.status == "executed"
    assert approved.undoable is True
    events = ctx.workspace.list_events(start="2026-12-01T00:00", end="2026-12-02T00:00")["events"]
    assert any(event["summary"] == "Test event" for event in events)

    undone = ctx.gate.undo(action.id)
    assert undone.undo_status == "undone"
    events = ctx.workspace.list_events(start="2026-12-01T00:00", end="2026-12-02T00:00")["events"]
    assert not any(event["summary"] == "Test event" for event in events)

    audit_events = [entry["event"] for entry in ctx.audit.list()]
    assert "action.executed" in audit_events
    assert "action.undone" in audit_events


def test_rejected_action_never_executes(ctx):
    before = event_count(ctx)
    action = make_action(ctx, "Rejected event")
    rejected = ctx.gate.reject(action.id)
    assert rejected.status == "rejected"
    assert event_count(ctx) == before
    with pytest.raises(ActionStateError):
        ctx.gate.approve(action.id)
    assert event_count(ctx) == before


def test_args_tampering_is_blocked(ctx):
    action = make_action(ctx, "Safe title")
    tampered = {
        "summary": "Tampered title",
        "start": "2026-12-01T09:00+05:30",
        "end": "2026-12-01T09:30+05:30",
    }
    ctx.db.execute(
        "UPDATE actions SET args = ? WHERE id = ?", (json.dumps(tampered), action.id)
    )
    with pytest.raises(ActionStateError):
        ctx.gate.approve(action.id)
    assert any(entry["event"] == "action.tampered" for entry in ctx.audit.list())


def test_duplicate_proposals_are_deduped(ctx):
    first = make_action(ctx, "Dedupe event")
    second = make_action(ctx, "Dedupe event")
    assert first.id == second.id


def test_unknown_action_raises(ctx):
    with pytest.raises(ActionNotFound):
        ctx.gate.approve("act_missing")


# -------------------------------------------------------------------- voice
def test_tts_without_key_raises(ctx):
    with pytest.raises(VoiceNotConfigured):
        ctx.voice.tts("hello")
