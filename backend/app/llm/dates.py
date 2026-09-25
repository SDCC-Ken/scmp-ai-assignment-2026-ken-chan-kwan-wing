"""Guard against dates the user never stated.

Small models (and sometimes big ones) fill today's date when a claim receipt date or a leave
date is missing: ``"Claim HKD 180 for a taxi"`` comes back with ``receipt_date`` = today. The
value would then look stated and the assistant would skip the question. The rule, applied by the
Ollama provider AND by the backend merge (defence in depth, so it also protects Gemini):

    a date field is kept only when the user's message contains a date expression (an ISO date,
    "22 Sep", "the 5th", "yesterday", a weekday, "next week", ...), or when the value is one the
    draft or an attached document already holds.

The check is deliberately coarse (it does not verify WHICH date): it only stops a date that
comes from nowhere. It never rejects a date the user wrote.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date

from app.llm.schemas import ClaimFields, LeaveFields

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_WEEKDAY = (
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|mon|tues?|wed|thu(?:rs?)?|fri|sat|sun)"
)
_NUMBER_WORD = r"(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"

_DATE_EXPRESSION = re.compile(
    "|".join(
        [
            r"\d{4}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{1,2}",  # 2026-09-22, 2026/9/22
            r"(?<![\d.])\d{1,2}\s*[/-]\s*\d{1,2}(?:\s*[/-]\s*\d{2,4})?(?![\d.])",  # 22/9, 22-9-26
            r"(?<![\d.])\d{1,2}\.\d{1,2}\.\d{2,4}(?![\d.])",  # 22.9.2026 (never "65.5")
            rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\b",  # 22 Sep, 22nd of September
            rf"\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b",  # Sep 22, September 22nd
            r"\b\d{1,2}(?:st|nd|rd|th)\b",  # the 5th
            r"\b(?:today|tonight|tomorrow|tmrw|tmr|yesterday)\b",
            rf"\b{_WEEKDAY}\b",
            r"\b(?:this|next|last|coming|past)\s+(?:week|month|weekend|year)\b",
            r"\b(?:last night|this morning|this afternoon|this evening)\b",
            rf"\b(?:\d+|{_NUMBER_WORD})\s+(?:working\s+|business\s+)?(?:days?|weeks?)\b",
            r"\b(?:by|another|extra|additional)\s+(?:a|an|one)\s+(?:more\s+|extra\s+)?"
            r"(?:day|week)\b",
            r"\b(?:a|one)\s+(?:day|week)\s+(?:ago|later|earlier|before|after)\b",
            # Chinese (Traditional and Simplified): today/yesterday/..., weekdays, 9月22日, 22號
            r"[今昨前明後后][日天晚朝]",
            r"大[前後后][日天]",
            r"[上下這这本][個个]?(?:星期|禮拜|礼拜|週|周)",
            r"(?:星期|禮拜|礼拜|週|周)[一二三四五六日天末]",
            r"\d{1,2}\s*月\s*\d{1,2}\s*[日號号]?",
            r"\d{1,2}\s*[日號号]",
        ]
    ),
    re.IGNORECASE,
)


def mentions_a_date(text: str | None) -> bool:
    """True when ``text`` contains any date expression (see the module docstring)."""
    return bool(text) and _DATE_EXPRESSION.search(text or "") is not None


def _known(values: Iterable[date | None]) -> set[date]:
    return {v for v in values if v is not None}


def leave_dates(fields: LeaveFields | None) -> set[date]:
    return _known([fields.start_date, fields.end_date]) if fields is not None else set()


def claim_dates(fields: ClaimFields | None) -> set[date]:
    return _known([fields.receipt_date]) if fields is not None else set()


def drop_unstated_dates(
    fields: LeaveFields | ClaimFields | None, message: str, known: Iterable[date] = ()
) -> tuple[LeaveFields | ClaimFields | None, list[str]]:
    """Clear the date fields the user did not state.

    ``known`` are dates the draft or a document already holds (a repeated value is not
    invented). Returns the (possibly emptied) fields and the names of the dropped fields.
    ``None`` in, ``None`` out; a leave / claim object left with no value at all becomes ``None``.
    """
    if fields is None or mentions_a_date(message):
        return fields, []
    keep = set(known)
    names = ("start_date", "end_date") if isinstance(fields, LeaveFields) else ("receipt_date",)
    dropped: list[str] = []
    update: dict[str, None] = {}
    for name in names:
        value = getattr(fields, name)
        if value is not None and value not in keep:
            update[name] = None
            dropped.append(name)
    if not dropped:
        return fields, []
    cleaned = fields.model_copy(update=update)
    if all(v is None for v in cleaned.model_dump().values()):
        return None, dropped
    return cleaned, dropped
