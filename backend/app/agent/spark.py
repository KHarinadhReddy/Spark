from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..config import Settings
from ..core.approval import Action, ApprovalGate
from ..core.audit import AuditLog
from ..core.guardrails import scan_untrusted, scan_user_request
from ..mcp.registry import Registry
from .deadlines import (
    Deadline,
    days_until,
    extract_dates,
    find_deadlines,
    format_date,
    humanize_days,
    parse_datetime,
    plus_minutes,
)
from .llm import BedrockPhraser

CONTACTS: dict[str, tuple[str, str]] = {
    "accounts": ("accounts@eastpoint.edu.in", "Accounts Office"),
    "fee": ("accounts@eastpoint.edu.in", "Accounts Office"),
    "exam": ("coe@eastpoint.edu.in", "Controller of Examinations"),
    "coe": ("coe@eastpoint.edu.in", "Controller of Examinations"),
    "library": ("library@eastpoint.edu.in", "Central Library"),
    "hostel": ("hostel@eastpoint.edu.in", "Hostel Office"),
    "mess": ("hostel@eastpoint.edu.in", "Hostel Office"),
    "placement": ("placements@eastpoint.edu.in", "Placement Cell"),
    "scholarship": ("scholarships@eastpoint.edu.in", "Scholarship Cell"),
    "professor": ("prof.sharma@eastpoint.edu.in", "Prof. Sharma"),
    "teacher": ("prof.sharma@eastpoint.edu.in", "Prof. Sharma"),
    "guide": ("prof.sharma@eastpoint.edu.in", "Prof. Sharma"),
}

DEADLINE_WORDS = re.compile(
    r"(last date|due date|due on|is due|are due|deadline|closes|close on|return (?:them )?by|"
    r"apply by|applications? close|register by|registration closes|pay by|payment is due|"
    r"submit by|submission deadline|before \d)",
    re.I,
)


def _short_title(subject: str, limit: int = 58) -> str:
    title = re.split(r"\s+[—–-]\s+", subject, maxsplit=1)[0].strip()
    title = title or subject
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def _fmt_time(iso: str) -> str:
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return moment.strftime("%I:%M %p").lstrip("0")


def _fmt_day(iso: str, language: str = "en") -> str:
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return format_date(moment.date(), language)


def _detect_language(text: str) -> str:
    return "hi" if re.search(r"[\u0900-\u097F]", text) else "en"


def _pick(language: str, english: str, hindi: str) -> str:
    return hindi if language == "hi" else english


@dataclass(slots=True)
class _StoredBrief:
    """Adapter so the existing brief/UI can read DB-backed deadlines."""

    subject: str
    sender: str
    when: date
    email_id: str
    snippet: str
    flagged: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "email_id": self.email_id,
            "subject": self.subject,
            "sender": self.sender,
            "date": self.when.isoformat(),
            "snippet": self.snippet,
            "flagged": self.flagged,
        }


@dataclass(slots=True)
class ChatResult:
    reply: str
    language: str
    intent: str
    cards: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    flags: list[dict[str, Any]] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "language": self.language,
            "intent": self.intent,
            "cards": self.cards,
            "sources": self.sources,
            "flags": self.flags,
        }


class SparkAgent:
    """Plans requests, runs read tools, and stages every write for approval."""

    def __init__(
        self,
        settings: Settings,
        registry: Registry,
        gate: ApprovalGate,
        workspace: Any,
        audit: AuditLog,
        llm: BedrockPhraser | None = None,
        store: Any = None,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.gate = gate
        self.workspace = workspace
        self.audit = audit
        self.llm = llm or BedrockPhraser(settings)
        self.store = store
        try:
            self.tz = ZoneInfo(settings.timezone)
        except Exception:
            self.tz = timezone(timedelta(hours=5, minutes=30))

    # ------------------------------------------------------------- utilities
    def now(self) -> datetime:
        return datetime.now(self.tz)

    @property
    def profile(self) -> dict[str, Any]:
        return getattr(self.workspace, "profile", {}) or {}

    def _name(self) -> str:
        return self.profile.get("name", "there")

    def _source_email(self, email: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "email",
            "id": email.get("id", ""),
            "title": email.get("subject", "(no subject)"),
            "subtitle": f"{email.get('from_name') or email.get('from', '')} · {_fmt_day(email.get('date', ''))}",
            "snippet": email.get("snippet", ""),
            "flagged": bool(email.get("flags")),
        }

    @staticmethod
    def _source_event(event: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "event",
            "id": event.get("id", ""),
            "title": event.get("summary", "(untitled)"),
            "subtitle": f"{_fmt_day(event.get('start', ''))} · {_fmt_time(event.get('start', ''))}",
            "snippet": event.get("location", "") or event.get("description", ""),
            "flagged": False,
        }

    @staticmethod
    def _source_file(file: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "file",
            "id": file.get("id", ""),
            "title": file.get("name", ""),
            "subtitle": _fmt_day(file.get("modified", "")),
            "snippet": (file.get("content", "") or file.get("snippet", ""))[:160],
            "flagged": bool(file.get("flags")),
        }

    def _event_window(self) -> tuple[datetime, datetime]:
        start = self.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)

    def _events_today(self, now: datetime | None = None) -> list[dict[str, Any]]:
        start = (now or self.now()).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.workspace.list_events(
            start=start.isoformat(), end=(start + timedelta(days=1)).isoformat(), limit=20
        )["events"]

    # ----------------------------------------------------------- public API
    def brief(
        self, language: str | None = None, now: datetime | None = None
    ) -> dict[str, Any]:
        language = language if language in {"en", "hi"} else "en"
        now = now or self.now()
        events = self._events_today(now)
        stored = self.store.list_deadlines(days=45) if self.store else []
        if stored:
            deadlines = [
                _StoredBrief(
                    subject=deadline.title,
                    sender=deadline.source,
                    when=deadline.due_date_value or now.date(),
                    email_id=deadline.source_id or deadline.id,
                    snippet=deadline.evidence,
                )
                for deadline in stored
            ]
        else:
            deadlines = find_deadlines(self.workspace, now)
        sources = [self._source_event(event) for event in events[:3]] + [
            self._source_email({"id": d.email_id, "subject": d.subject, "from_name": d.sender})
            for d in deadlines[:2]
        ]
        flags = [
            {"rule": "untrusted-instruction", "snippet": d.snippet, "source": d.subject}
            for d in deadlines
            if d.flagged
        ]
        name = self._name()
        if language == "hi":
            if events:
                agenda = "、".join(
                    f"{event['summary']} ({_fmt_time(event['start'])})" for event in events[:3]
                )
                text = f"नमस्ते {name}! आज आपके {len(events)} कार्यक्रम हैं — {agenda}।"
            else:
                text = f"नमस्ते {name}! आज कैलेंडर खाली है।"
            if deadlines:
                nearest = deadlines[0]
                text += (
                    f" सबसे नज़दीकी डेडलाइन “{_short_title(nearest.subject)}” है — "
                    f"{format_date(nearest.when, 'hi')} ({humanize_days(nearest.when, now.date(), 'hi')})।"
                )
            text += " कैलेंडर में जोड़ने के लिए डेडलाइन स्कैन चलाइए — मैं कार्ड तैयार कर दूँगा।"
        else:
            if events:
                agenda = ", ".join(
                    f"{event['summary']} at {_fmt_time(event['start'])}" for event in events[:3]
                )
                text = f"Good morning, {name}. You have {len(events)} things today: {agenda}."
            else:
                text = f"Good morning, {name}. Your calendar is clear today."
            if deadlines:
                nearest = deadlines[0]
                text += (
                    f" Nearest deadline: {_short_title(nearest.subject)} on "
                    f"{format_date(nearest.when)} ({humanize_days(nearest.when, now.date())})."
                )
            text += " Say “find deadlines in my emails” and I'll prepare calendar cards for you."
        if flags:
            text += _pick(
                language,
                " One email looks like it is trying to give me instructions — I ignored it.",
                " एक ईमेल मुझे निर्देश देने की कोशिश कर रहा है — मैंने उसे अनदेखा किया।",
            )
        self.audit.log(
            "agent.brief",
            detail={"events": len(events), "deadlines": len(deadlines)},
        )
        return {
            "text": text,
            "language": language,
            "date": now.date().isoformat(),
            "events": events,
            "deadlines": [deadline.public() for deadline in deadlines],
            "flags": flags,
            "sources": sources,
        }

    def handle(
        self,
        message: str,
        language: str | None = None,
        *,
        now: datetime | None = None,
    ) -> ChatResult:
        text = (message or "").strip()
        if not text:
            return ChatResult(
                reply="Ask me about your deadlines, calendar or inbox.",
                language="en",
                intent="empty",
            )
        lang = language if language in {"en", "hi"} else _detect_language(text)
        now = now or self.now()

        user_flags = scan_user_request(text)
        if user_flags:
            self.audit.log(
                "guardrail.blocked",
                detail={"rules": [flag.rule for flag in user_flags], "request": text[:160]},
            )
            return ChatResult(
                reply=_pick(
                    lang,
                    "I can't do that. I only read your data and prepare drafts or events — "
                    "writes need your explicit approval, and I never share OTPs, passwords or tokens. "
                    "Try “Find deadlines in my emails”.",
                    "मैं यह नहीं कर सकता। मैं सिर्फ़ आपका डेटा पढ़ता हूँ और ड्राफ़्ट या इवेंट तैयार करता हूँ — "
                    "कुछ भी बदलने के लिए आपकी मंज़ूरी ज़रूरी है, और मैं OTP, पासवर्ड या टोकन कभी साझा नहीं करता। "
                    "“मेरे ईमेल में डेडलाइन खोजो” आज़माइए।",
                ),
                language=lang,
                intent="blocked",
                flags=[{**flag.as_dict(), "source": "request"} for flag in user_flags],
            )

        intent = self._classify(text)
        self.audit.log(
            "agent.query", detail={"intent": intent, "chars": len(text), "language": lang}
        )
        if intent == "brief":
            payload = self.brief(lang, now)
            return ChatResult(
                reply=payload["text"],
                language=lang,
                intent="brief",
                sources=payload["sources"],
                flags=payload["flags"],
            )
        if intent == "deadlines":
            return self._deadline_scan(lang, now)
        if intent == "event":
            return self._create_event(text, lang, now)
        if intent == "draft":
            return self._draft_email(text, lang)
        if intent == "files":
            return self._find_files(text, lang)
        if intent == "help":
            return ChatResult(reply=self._help(lang), language=lang, intent="help")
        return self._answer_question(text, lang, now)

    def add_deadline_to_calendar(
        self, email_id: str, language: str = "en"
    ) -> tuple[dict[str, Any], str]:
        now = self.now()
        deadlines = find_deadlines(self.workspace, now)
        deadline = next((item for item in deadlines if item.email_id == email_id), None)
        if deadline is None:
            raise KeyError(f"no future deadline for email {email_id}")
        action = self._propose_deadline_event(deadline, now, language)
        reply = _pick(
            language,
            f"Card ready: “{_short_title(deadline.subject)}” on {format_date(deadline.when)}. "
            "Nothing is on your calendar until you approve.",
            f"कार्ड तैयार है: “{_short_title(deadline.subject)}”, {format_date(deadline.when, 'hi')}। "
            "आपकी मंज़ूरी तक कैलेंडर में कुछ नहीं जुड़ेगा।",
        )
        return action.public(), reply

    # ------------------------------------------------------------- intents
    def _classify(self, text: str) -> str:
        lower = text.lower()
        if re.search(
            r"\b(good morning|good evening|morning brief|daily brief|my brief|brief me|"
            r"start my day|what'?s today|my day)\b",
            lower,
        ) or re.search(r"(मॉर्निंग ब्रीफ़|मेरा ब्रीफ़|आज का ब्रीफ़|दिन की शुरुआत)", lower):
            return "brief"
        if re.search(r"\b(when|what date|what time)\b.*\b(due|deadline|exam|fee|interview)\b", lower):
            return "qa"
        if re.search(r"\b(deadline|deadlines|last date|due dates?|scan|radar)\b", lower) or re.search(
            r"\b(what'?s|what is|anything)\b.*\bdue\b", lower
        ) or re.search(r"(डेडलाइन|अंतिम तारीख़|आख़िरी तारीख|स्कैन)", lower):
            return "deadlines"
        if re.search(r"\b(address|who are you|what can you do|help|commands|features)\b", lower) or re.search(
            r"(मदद|क्या कर सकते|तुम कौन)", lower
        ):
            return "help"
        if (
            re.search(r"\b(add|create|schedule|put|book)\b", lower)
            and re.search(r"\b(event|meeting|class|reminder|calendar|slot)\b", lower)
        ) or re.search(r"(कैलेंडर में (जोड़ो|जोड़िए|डालो)|इवेंट बनाओ)", lower):
            return "event"
        if (
            re.match(r"^(please\s+)?(add|create|schedule|put|book)\b", lower)
            and re.search(
                r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|"
                r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|"
                r"\d{1,2}[:/]\d{1,2}",
                lower,
            )
        ):
            return "event"
        if (
            re.search(r"\b(draft|compose|write)\b", lower)
            and re.search(r"\b(email|mail|note|reminder)\b", lower)
        ) or re.search(r"(ड्राफ़्ट|ड्राफ्ट).*(ईमेल|मेल|रिमाइंडर)", lower):
            return "draft"
        if (
            re.search(r"\b(drive|files?|documents?|pdf|docs|notes)\b", lower)
            and re.search(r"\b(find|search|show|where|open|read|my)\b", lower)
        ) or re.search(r"(फ़ाइल|फाइल|दस्तावेज़).*(ढूँढ|खोज|दिखाओ)", lower):
            return "files"
        if re.search(r"\b(hello|hi|hey|namaste)\b", lower) or re.search(r"(नमस्ते|नमस्कार)", lower):
            return "help"
        return "qa"

    # ------------------------------------------------------------- deadlines
    def _deadline_scan(self, language: str, now: datetime) -> ChatResult:
        deadlines = find_deadlines(self.workspace, now)
        sources: list[dict[str, Any]] = []
        flags: list[dict[str, Any]] = []
        for deadline in deadlines:
            email = {
                "id": deadline.email_id,
                "subject": deadline.subject,
                "from_name": deadline.sender,
                "snippet": deadline.snippet,
                "flags": [{"rule": "untrusted-instruction"}] if deadline.flagged else [],
            }
            sources.append(self._source_email(email))

        inbox = self.workspace.search_emails(query="", limit=20)["emails"]
        flagged_emails = [email for email in inbox if email.get("flags")]
        for email in flagged_emails:
            sources.append(self._source_email(email))
            first = email["flags"][0]
            flags.append(
                {
                    "rule": first.get("rule", "untrusted-instruction"),
                    "snippet": first.get("snippet", ""),
                    "source": email.get("subject", ""),
                }
            )

        if not deadlines:
            return ChatResult(
                reply=_pick(
                    language,
                    "I couldn't find any deadline emails right now. Connect Gmail for live data, "
                    "or ask me “what's on my calendar today?”.",
                    "अभी कोई डेडलाइन ईमेल नहीं मिला। लाइव डेटा के लिए Gmail जोड़िए, "
                    "या पूछिए “आज कैलेंडर में क्या है?”।",
                ),
                language=language,
                intent="deadlines",
            )

        cards = []
        for deadline in deadlines[:4]:
            cards.append(self._propose_deadline_event(deadline, now, language).public())

        nearest = deadlines[0]
        if language == "hi":
            reply = (
                f"आपके ईमेल में {len(deadlines)} डेडलाइन मिलीं। मैंने {len(cards)} कार्ड तैयार किए हैं — "
                "आपकी स्वीकृति के बाद ही कैलेंडर में जोड़े जाएँगे। "
                f"सबसे नज़दीकी: “{_short_title(nearest.subject)}”, {format_date(nearest.when, 'hi')} "
                f"({humanize_days(nearest.when, now.date(), 'hi')})।"
            )
        else:
            reply = (
                f"I found {len(deadlines)} deadlines across your inbox. I've prepared {len(cards)} "
                "calendar cards — nothing is added until you approve. "
                f"Nearest: “{_short_title(nearest.subject)}” on {format_date(nearest.when)} "
                f"({humanize_days(nearest.when, now.date())})."
            )
        if flags:
            reply += _pick(
                language,
                " ⚠ One email contains instructions aimed at me; I've treated it as data and ignored it.",
                " ⚠ एक ईमेल में मेरे लिए निर्देश हैं; मैंने उसे डेटा मानकर अनदेखा किया।",
            )
        self.audit.log(
            "tool.read",
            tool="gmail.search_emails",
            detail={"deadlines": len(deadlines), "flagged": len(flags)},
        )
        if flags:
            self.audit.log(
                "guardrail.flagged",
                tool="gmail.search_emails",
                detail={
                    "reason": "prompt injection in email",
                    "sources": [email["id"] for email in flagged_emails],
                },
            )
        return ChatResult(
            reply=reply,
            language=language,
            intent="deadlines",
            cards=cards,
            sources=sources,
            flags=flags,
            facts=[f"{d.subject} — deadline {format_date(d.when)} (from {d.sender})" for d in deadlines],
        )

    def _propose_deadline_event(
        self, deadline: Deadline, now: datetime, language: str
    ) -> Action:
        start = datetime.combine(deadline.when, time(9, 0), tzinfo=self.tz)
        end = start + timedelta(minutes=30)
        title = _short_title(deadline.subject)
        args = {
            "summary": f"Deadline: {title}",
            "start": start.isoformat(timespec="minutes"),
            "end": end.isoformat(timespec="minutes"),
            "description": (
                f"Detected in the email “{deadline.subject}” from {deadline.sender}.\n\n"
                f"{deadline.snippet}\n\nAdded by Spark after student approval."
            ),
        }
        preview = {
            "title": f"Add “{title}” to Calendar",
            "summary": f"{format_date(deadline.when, language)} · 9:00–9:30 AM IST",
            "fields": [
                {"label": "Event", "value": f"Deadline: {title}"},
                {"label": "Date", "value": format_date(deadline.when, language)},
                {"label": "Time", "value": "9:00 AM – 9:30 AM IST"},
                {"label": "Source email", "value": deadline.subject},
                {"label": "From", "value": deadline.sender},
            ],
            "note": _pick(
                language,
                "This is a reminder event. It will be created only after you approve.",
                "यह एक रिमाइंडर इवेंट है। आपकी स्वीकृति के बाद ही बनेगा।",
            ),
            "undo_hint": "You can undo this from Activity for 24 hours.",
        }
        return self.gate.propose(
            "calendar.create_event", args, preview, source=f"email:{deadline.email_id}"
        )

    # ---------------------------------------------------------------- events
    def _create_event(self, text: str, language: str, now: datetime) -> ChatResult:
        moment = parse_datetime(text, now)
        if moment is None:
            return ChatResult(
                reply=_pick(
                    language,
                    "I can add that, but I need a date. Try “Add a study block on 29 Nov at 3 PM”.",
                    "मैं जोड़ सकता हूँ, लेकिन तारीख़ चाहिए। ऐसे कहिए: “29 नवंबर को 3 बजे स्टडी ब्लॉक जोड़ो”।",
                ),
                language=language,
                intent="event",
            )
        title = self._event_title(text, moment)
        end = plus_minutes(moment, 30)
        args = {
            "summary": title,
            "start": moment.isoformat(timespec="minutes"),
            "end": end.isoformat(timespec="minutes"),
            "description": "Created with Spark after student approval.",
        }
        preview = {
            "title": f"Add “{title}” to Calendar",
            "summary": f"{format_date(moment.date(), language)} · {_fmt_time(moment.isoformat())}",
            "fields": [
                {"label": "Event", "value": title},
                {"label": "Date", "value": format_date(moment.date(), language)},
                {"label": "Time", "value": f"{_fmt_time(moment.isoformat())} – {_fmt_time(end.isoformat())} IST"},
                {"label": "Calendar", "value": "Primary"},
            ],
            "note": _pick(
                language,
                "Nothing is created until you approve this card.",
                "आपकी स्वीकृति तक कुछ नहीं बनेगा।",
            ),
            "undo_hint": "Undo is available from Activity.",
        }
        action = self.gate.propose("calendar.create_event", args, preview, source="user")
        reply = _pick(
            language,
            f"I've prepared “{title}” for {format_date(moment.date())} at "
            f"{_fmt_time(moment.isoformat())}. Approve the card and it lands on your calendar.",
            f"मैंने “{title}” {format_date(moment.date(), 'hi')} को {_fmt_time(moment.isoformat())} बजे के लिए तैयार किया है। "
            "कार्ड स्वीकृत करते ही कैलेंडर में जुड़ जाएगा।",
        )
        return ChatResult(
            reply=reply,
            language=language,
            intent="event",
            cards=[action.public()],
        )

    @staticmethod
    def _event_title(text: str, moment: datetime) -> str:
        cleaned = re.sub(
            r"^(please\s+)?(add|create|schedule|put|book)\s+(an?\s+)?", "", text.strip(), flags=re.I
        )
        cleaned = re.sub(
            r"\b(to|on|in|at)\b.*$", "", cleaned, flags=re.I
        ).strip(" .,-")
        cleaned = re.sub(r"\b(event|meeting|slot)\b$", "", cleaned, flags=re.I).strip()
        return (cleaned or "New event")[:80].strip().capitalize()

    # ---------------------------------------------------------------- drafts
    def _draft_email(self, text: str, language: str) -> ChatResult:
        recipient, recipient_name = self._resolve_recipient(text)
        topic = self._draft_topic(text)
        subject = f"Reminder: {topic[:70]}"
        name = self._name()
        body = (
            f"Respected {recipient_name or 'Sir/Madam'},\n\n"
            f"I hope you are doing well. This is a gentle reminder regarding {topic}.\n\n"
            "Could you please confirm the next step, or let me know if anything is pending from my side?\n\n"
            f"Thank you,\n{name}\n{self.profile.get('usn', '')}".strip()
        )
        args = {"to": recipient, "subject": subject, "body": body}
        preview = {
            "title": f"Save draft: “{subject}”",
            "summary": (f"To {recipient_name or 'recipient to be added'} · saved to Gmail Drafts"),
            "fields": [
                {"label": "To", "value": recipient or "Add recipient in Gmail"},
                {"label": "Subject", "value": subject},
                {"label": "Body", "value": body[:220] + ("…" if len(body) > 220 else "")},
                {"label": "Delivery", "value": "Draft only — never sent automatically"},
            ],
            "note": _pick(
                language,
                "Approving saves this to Gmail Drafts. Spark cannot send email.",
                "स्वीकृति से यह Gmail ड्राफ़्ट में सेव होगा। Spark ईमेल भेज नहीं सकता।",
            ),
            "undo_hint": "Undo deletes the draft.",
        }
        action = self.gate.propose("gmail.create_draft", args, preview, source="user")
        reply = _pick(
            language,
            f"I've drafted a reminder to {recipient_name or 'your recipient'} about {topic}. "
            "It will be saved as a Gmail draft, not sent. Review the card and approve to save it.",
            f"मैंने {recipient_name or 'प्राप्तकर्ता'} के लिए {topic} पर रिमाइंडर ड्राफ़्ट किया है। "
            "यह Gmail ड्राफ़्ट में सेव होगा, भेजा नहीं जाएगा। कार्ड देखकर स्वीकृत करें।",
        )
        return ChatResult(
            reply=reply,
            language=language,
            intent="draft",
            cards=[action.public()],
        )

    @staticmethod
    def _resolve_recipient(text: str) -> tuple[str, str]:
        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        lower = text.lower()
        for key, (email, name) in CONTACTS.items():
            if key in lower and not email_match:
                return email, name
        if email_match:
            address = email_match.group(0)
            return address, address.split("@")[0].replace(".", " ").title()
        return "", ""

    @staticmethod
    def _draft_topic(text: str) -> str:
        cleaned = re.sub(r"^(please\s+)?(draft|compose|write)\s+(an?\s+)?", "", text.strip(), flags=re.I)
        cleaned = re.sub(r"^(email|mail|reminder|note)\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"^(to|for)\s+[^,.;]+?\s+(about|regarding|on)\s+", "", cleaned, flags=re.I)
        cleaned = re.sub(r"^(to|for)\s+", "", cleaned, flags=re.I)
        cleaned = cleaned.strip(" .,")
        return (cleaned or "the pending item")[:90]

    # ----------------------------------------------------------------- files
    def _find_files(self, text: str, language: str) -> ChatResult:
        query = re.sub(
            r"\b(find|search|show|open|read|my|in|on|drive|file|files|document|documents|"
            r"the|me|please|for|about)\b",
            " ",
            text,
            flags=re.I,
        ).strip()
        result = self.workspace.search_files(query=query or text, limit=5)
        files = result["files"]
        if not files:
            return ChatResult(
                reply=_pick(
                    language,
                    "I couldn't find a matching file in Drive. Try naming the document, e.g. "
                    "“find the exam form guidelines”.",
                    "Drive में मिलता फ़ाइल नहीं मिला। दस्तावेज़ का नाम बताइए, जैसे "
                    "“exam form guidelines ढूँढो”।",
                ),
                language=language,
                intent="files",
            )
        lines = []
        contents = []
        for file in files[:3]:
            lines.append(f"“{file['name']}”")
            if re.search(r"\b(what|content|inside|summary|read|checklist)\b", text, re.I):
                try:
                    detail = self.workspace.read_file(file["id"])
                    contents.append((file, detail.get("content", "")))
                except Exception:
                    pass
        if contents:
            file, content = contents[0]
            reply = _pick(
                language,
                f"Here's what's inside “{file['name']}”: {content[:280]}"
                + ("…" if len(content) > 280 else ""),
                f"“{file['name']}” में यह है: {content[:280]}"
                + ("…" if len(content) > 280 else ""),
            )
        else:
            reply = _pick(
                language,
                "I found " + ", ".join(lines) + " in Drive. Ask me to read one, or search with a different name.",
                "Drive में मुझे " + ", ".join(lines) + " मिलीं। किसी को पढ़ने के लिए कहिए, या दूसरा नाम आज़माइए।",
            )
        self.audit.log("tool.read", tool="drive.search_files", detail={"files": len(files)})
        return ChatResult(
            reply=reply,
            language=language,
            intent="files",
            sources=[self._source_file(file) for file in files[:4]],
            facts=[f"{f['name']} — {f.get('content', '')[:120]}" for f in files],
        )

    # ------------------------------------------------------------------- Q&A
    def _answer_question(self, text: str, language: str, now: datetime) -> ChatResult:
        sources: list[dict[str, Any]] = []
        flags: list[dict[str, Any]] = []
        facts: list[str] = []

        events = self.workspace.list_events(
            start=now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
            end=(now + timedelta(days=7)).isoformat(),
            limit=10,
        )["events"]
        emails = self.workspace.search_emails(query=text, limit=4)["emails"]

        asked_schedule = bool(
            re.search(
                r"\b(calendar|schedule|classes|class|today|tomorrow|week)\b", text, re.I
            )
            or re.search(r"(कैलेंडर|आज|कल|कक्षा|क्लास|शेड्यूल)", text)
        )
        if asked_schedule and events:
            today = [event for event in events if event["start"][:10] == now.date().isoformat()]
            shown = today or events[:3]
            label = "today" if today else "in the next 7 days"
            lines = " · ".join(
                f"{event['summary']} at {_fmt_time(event['start'])}" for event in shown[:4]
            )
            reply = _pick(
                language,
                f"On your calendar {label}: {lines}.",
                f"{'आज' if today else 'अगले 7 दिनों में'} कैलेंडर पर: {lines}।",
            )
            sources.extend(self._source_event(event) for event in events[:4])
            return ChatResult(
                reply=reply,
                language=language,
                intent="qa",
                sources=sources,
                facts=[f"{e['summary']} at {_fmt_time(e['start'])} on {_fmt_day(e['start'])}" for e in events[:4]],
            )

        email_answer = None
        for email in emails:
            detail = self.workspace.read_email(email["id"])
            body = detail.get("body", "")
            hits = [
                hit
                for hit in extract_dates(body)
                if hit.value >= now.date()
            ]
            if email.get("flags"):
                flags.append(
                    {"rule": "untrusted-instruction", "snippet": detail.get("snippet", ""), "source": email["subject"]}
                )
                self.audit.log(
                    "guardrail.flagged",
                    tool="gmail.read_email",
                    detail={"email_id": email["id"], "reason": "prompt injection"},
                )
                continue
            snippet = re.sub(r"\s+", " ", body)[:220]
            sources.append(self._source_email(detail))
            facts.append(f"{email['subject']} from {email.get('from_name')}: {snippet}")
            if hits:
                email_answer = _pick(
                    language,
                    f"“{email['subject']}” from {email.get('from_name') or email.get('from')} gives "
                    f"{format_date(hits[0].value)}. The email says: {self._context(body, hits[0].matched)}",
                    f"“{email['subject']}” ({email.get('from_name') or email.get('from')}) के अनुसार तारीख़ "
                    f"{format_date(hits[0].value, 'hi')} है। ईमेल में लिखा है: {self._context(body, hits[0].matched)}",
                )
                break
            if email_answer is None:
                email_answer = _pick(
                    language,
                    f"From “{email['subject']}” ({email.get('from_name') or email.get('from')}): {snippet}",
                    f"“{email['subject']}” ({email.get('from_name') or email.get('from')}) से: {snippet}",
                )
        if email_answer:
            reply = email_answer
            if flags:
                reply += _pick(
                    language,
                    " ⚠ Another matching email tried to instruct me; I ignored its instructions.",
                    " ⚠ एक और ईमेल मुझे निर्देश देने की कोशिश कर रहा था; मैंने उसे अनदेखा किया।",
                )
            if self.llm.configured:
                phrased = self.llm.phrase(
                    message=text, language=language, facts=facts, sources=sources
                )
                if phrased:
                    reply = phrased
            return ChatResult(
                reply=reply,
                language=language,
                intent="qa",
                sources=sources,
                flags=flags,
                facts=facts,
            )

        # fall back to a file answer
        files = self.workspace.search_files(query=text, limit=3)["files"]
        if files:
            return self._find_files(text, language)

        help_text = self._help(language)
        if self.llm.configured and facts:
            phrased = self.llm.phrase(
                message=text, language=language, facts=facts, sources=sources
            )
            if phrased:
                help_text = phrased
        return ChatResult(
            reply=_pick(
                language,
                "I couldn't find that in your current inbox, calendar or Drive. I can run a morning "
                "brief, scan for deadlines, answer questions about your emails, add events, or draft "
                "an email — all writes wait for your approval.",
                "यह आपके ईमेल, कैलेंडर या Drive में नहीं मिला। मैं मॉर्निंग ब्रीफ़, डेडलाइन स्कैन, "
                "ईमेल के सवालों के जवाब, इवेंट और ड्राफ़्ट बना सकता हूँ — बदलाव आपकी मंज़ूरी के बाद ही होंगे।",
            ),
            language=language,
            intent="qa",
            flags=flags,
        )

    @staticmethod
    def _context(body: str, needle: str) -> str:
        clean = re.sub(r"\s+", " ", body)
        index = clean.lower().find(needle.lower())
        if index < 0:
            return clean[:160]
        left = max(0, index - 70)
        right = min(len(clean), index + len(needle) + 80)
        return ("… " if left else "") + clean[left:right].strip() + (" …" if right < len(clean) else "")

    # ------------------------------------------------------------------- help
    def _help(self, language: str) -> str:
        if language == "hi":
            return (
                "मैं Spark हूँ — छात्रों के रोज़मर्रा के कामों के लिए वॉइस-फ़र्स्ट सहायक। "
                "मैं कैलेंडर, Gmail और Drive पढ़ता हूँ, और कुछ भी बदलने से पहले आपकी मंज़ूरी लेता हूँ।\n\n"
                "आज़माइए:\n• “मेरा मॉर्निंग ब्रीफ़ दो”\n• “मेरे ईमेल में डेडलाइन खोजो”\n"
                "• “इस हफ़्ते क्या ड्यू है?”\n• “अकाउंट्स ऑफ़िस को रिमाइंडर ड्राफ़्ट करो”\n"
                "• “आज कैलेंडर पर क्या है?”"
            )
        return (
            "I'm Spark — a voice-first assistant for student admin. I read your Calendar, Gmail "
            "and Drive, and I act only after you approve.\n\n"
            "Try:\n• “Give me my morning brief”\n• “Find deadlines in my emails”\n"
            "• “What's due this week?”\n• “Draft a reminder to the accounts office”\n"
            "• “What's on my calendar today?”\n\n"
            "Every write shows a preview card first, and everything is logged and undoable."
        )
