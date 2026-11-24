from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..mcp.mock_workspace import MockWorkspace
from ..mcp.google_workspace import GoogleWorkspace

MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

MONTH_NAMES = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_NAMES_HI = [
    "", "जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून",
    "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर",
]

_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
_DAY_MONTH_YEAR = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_RE})[a-z]*\.?,?\s+(\d{{4}})\b", re.I)
_MONTH_DAY_YEAR = re.compile(rf"\b({_MONTH_RE})[a-z]*\.?\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")

DEADLINE_CONTEXT = re.compile(
    r"(last date|due\b|deadline|closes?\b|return (?:them )?by|apply (?:by|before)|"
    r"applications? close|register (?:by|before)|registration (?:closes|window)|"
    r"pay(?:ment)? (?:by|before|is due)|submit (?:by|before)|submission deadline|"
    r"renew (?:online )?by)",
    re.I,
)


@dataclass(slots=True)
class DateHit:
    value: date
    matched: str


@dataclass(slots=True)
class Deadline:
    email_id: str
    subject: str
    sender: str
    when: date
    snippet: str
    flagged: bool

    def public(self) -> dict:
        return {
            "email_id": self.email_id,
            "subject": self.subject,
            "sender": self.sender,
            "date": self.when.isoformat(),
            "snippet": self.snippet,
            "flagged": self.flagged,
        }


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_dates(text: str) -> list[DateHit]:
    hits: list[DateHit] = []
    for match in _DAY_MONTH_YEAR.finditer(text):
        day, month_name, year = match.groups()
        month = MONTHS.get(month_name.lower())
        value = _safe_date(int(year), month, int(day)) if month else None
        if value:
            hits.append(DateHit(value=value, matched=match.group(0)))
    for match in _MONTH_DAY_YEAR.finditer(text):
        month_name, day, year = match.groups()
        month = MONTHS.get(month_name.lower())
        value = _safe_date(int(year), month, int(day)) if month else None
        if value:
            hits.append(DateHit(value=value, matched=match.group(0)))
    for match in _ISO.finditer(text):
        year, month, day = (int(part) for part in match.groups())
        value = _safe_date(year, month, day)
        if value:
            hits.append(DateHit(value=value, matched=match.group(0)))
    for match in _DMY.finditer(text):
        day, month, year = (int(part) for part in match.groups())
        value = _safe_date(year, month, day)
        if value:
            hits.append(DateHit(value=value, matched=match.group(0)))
    unique: dict[date, DateHit] = {}
    for hit in hits:
        unique.setdefault(hit.value, hit)
    return sorted(unique.values(), key=lambda hit: hit.value)


def _snippet_for(body: str, needle: str) -> str:
    cleaned = re.sub(r"\s+", " ", body).strip()
    index = cleaned.lower().find(needle.lower())
    if index < 0:
        return cleaned[:180]
    left = max(0, index - 90)
    right = min(len(cleaned), index + len(needle) + 110)
    prefix = "… " if left else ""
    suffix = " …" if right < len(cleaned) else ""
    return f"{prefix}{cleaned[left:right].strip()}{suffix}"


def find_deadlines(
    workspace: MockWorkspace | GoogleWorkspace,
    now: datetime,
    *,
    limit: int = 6,
) -> list[Deadline]:
    today = now.date()
    result = workspace.search_emails(query="", limit=25)
    deadlines: list[Deadline] = []
    for email in result["emails"]:
        body = email.get("snippet", "")
        if hasattr(workspace, "read_email"):
            try:
                body = workspace.read_email(email["id"]).get("body", body)
            except Exception:
                pass
        hits = []
        for hit in extract_dates(body):
            if hit.value < today:
                continue
            index = body.lower().find(hit.matched.lower())
            context = body[max(0, index - 110) : index + len(hit.matched) + 90]
            if DEADLINE_CONTEXT.search(context):
                hits.append(hit)
        if not hits:
            continue
        first = hits[0]
        deadlines.append(
            Deadline(
                email_id=email["id"],
                subject=email["subject"],
                sender=email.get("from_name") or email.get("from", ""),
                when=first.value,
                snippet=_snippet_for(body, first.matched),
                flagged=bool(email.get("flags")),
            )
        )
    deadlines.sort(key=lambda item: (item.when, item.subject))
    return deadlines[:limit]


def format_date(value: date, language: str = "en") -> str:
    if language == "hi":
        return f"{value.day:02d} {MONTH_NAMES_HI[value.month]} {value.year}"
    return f"{value.day:02d} {MONTH_NAMES[value.month]} {value.year}"


def days_until(value: date, today: date) -> int:
    return (value - today).days


def humanize_days(value: date, today: date, language: str = "en") -> str:
    delta = days_until(value, today)
    if language == "hi":
        if delta <= 0:
            return "आज"
        if delta == 1:
            return "कल"
        return f"{delta} दिन में"
    if delta <= 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    return f"in {delta} days"


def parse_datetime(text: str, now: datetime) -> datetime | None:
    """Pick the first date in free text; default to 09:00 local if no time is given."""
    hits = extract_dates(text)
    hits = [hit for hit in hits if hit.value >= now.date()]
    value: date | None = hits[0].value if hits else None
    if value is None:
        day_month = re.search(rf"\b(\d{{1,2}})\s+({_MONTH_RE})\b", text, re.I)
        if day_month:
            month = MONTHS.get(day_month.group(2).lower())
            if month:
                candidate = _safe_date(now.year, month, int(day_month.group(1)))
                if candidate:
                    if candidate < now.date():
                        candidate = _safe_date(now.year + 1, month, int(day_month.group(1)))
                    value = candidate
        if value is None and re.search(r"\btomorrow\b", text, re.I):
            value = now.date() + timedelta(days=1)
        if value is None and re.search(r"\btoday\b", text, re.I):
            value = now.date()
    if value is None:
        return None
    hour, minute = 9, 0
    time_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text, re.I)
    if time_match:
        hour = int(time_match.group(1)) % 12
        minute = int(time_match.group(2) or 0)
        if time_match.group(3).lower() == "pm":
            hour += 12
    elif re.search(r"\b(\d{1,2}):(\d{2})\b", text):
        clock = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
        hour, minute = int(clock.group(1)), int(clock.group(2))
    return now.replace(year=value.year, month=value.month, day=value.day, hour=hour, minute=minute, second=0, microsecond=0)


def plus_minutes(moment: datetime, minutes: int = 30) -> datetime:
    return moment + timedelta(minutes=minutes)
