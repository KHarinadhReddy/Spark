from __future__ import annotations

import re
from dataclasses import dataclass

# Emails, notices and file contents are data, never instructions. These patterns flag
# text that looks like it is trying to steer the agent, so the UI can surface it and
# the orchestrator can refuse to act on it.
_INJECTION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override-instructions",
        re.compile(r"ignore (?:all |any )?(?:previous|prior|above|earlier) (?:instructions|rules|prompts)", re.I),
    ),
    (
        "role-hijack",
        re.compile(r"you are now (?:in )?(?:admin|developer|system|root|god) mode", re.I),
    ),
    (
        "credential-exfiltration",
        re.compile(r"(?:send|email|share|reply with).{0,48}(?:otp|password|pin|token|secret|aadhaar|pan|card number)", re.I),
    ),
    (
        "bypass-approval",
        re.compile(r"(?:without|skip|bypass).{0,24}(?:asking|approval|confirmation|permission)", re.I),
    ),
    (
        "state-change-command",
        re.compile(r"(?:mark .{0,35}(?:paid|approved|submitted|verified)|approve (?:this|the) (?:action|payment|request) automatically)", re.I),
    ),
    (
        "disregard-policy",
        re.compile(r"disregard .{0,24}(?:instructions|policy|rules|guardrails)", re.I),
    ),
    (
        "payment-redirect",
        re.compile(r"(?:wire transfer|gift card|bitcoin wallet|pay to this upi)", re.I),
    ),
    (
        "urgent-click",
        re.compile(r"(?:click|open) (?:this|the|here).{0,20}(?:link|url).{0,24}(?:verify|claim|unlock)", re.I),
    ),
)

_USER_ABUSE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "credential-exfiltration",
        re.compile(r"(?:send|share|tell|read).{0,32}(?:otp|password|pin|aadhaar|pan)", re.I),
    ),
    (
        "bypass-approval",
        re.compile(r"(?:approve|execute|run|do).{0,32}(?:without|skip|bypass).{0,24}(?:asking|approval|confirmation|permission)", re.I),
    ),
    (
        "mass-destructive",
        re.compile(r"(?:delete|wipe|erase).{0,24}(?:all|every).{0,20}(?:email|event|file|calendar)", re.I),
    ),
)


@dataclass(frozen=True)
class Flag:
    rule: str
    snippet: str

    def as_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "snippet": self.snippet}


def _snippet(text: str, start: int, end: int, padding: int = 46) -> str:
    left = max(0, start - padding)
    right = min(len(text), end + padding)
    cleaned = re.sub(r"\s+", " ", text[left:right]).strip()
    prefix = "… " if left else ""
    suffix = " …" if right < len(text) else ""
    return f"{prefix}{cleaned}{suffix}"


def scan_untrusted(text: str) -> list[Flag]:
    """Return injection flags found in third-party content (email/notice/file text)."""
    if not text:
        return []
    flags: list[Flag] = []
    for rule, pattern in _INJECTION_RULES:
        for match in pattern.finditer(text):
            flags.append(Flag(rule=rule, snippet=_snippet(text, match.start(), match.end())))
            if len(flags) >= 3:
                return flags
    return flags


def scan_user_request(text: str) -> list[Flag]:
    """Return flags for requests that try to talk the agent out of its guardrails."""
    if not text:
        return []
    flags: list[Flag] = []
    for rule, pattern in _USER_ABUSE_RULES:
        for match in pattern.finditer(text):
            flags.append(Flag(rule=rule, snippet=_snippet(text, match.start(), match.end())))
            if len(flags) >= 3:
                return flags
    return flags


def wrap_untrusted(text: str) -> str:
    """Delimiter used when third-party content is passed to an LLM."""
    safe = text.replace("<<<UNTRUSTED", "[content]").replace("UNTRUSTED>>>", "[/content]")
    return f"<<<UNTRUSTED\n{safe}\nUNTRUSTED>>>"
