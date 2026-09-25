"""Deterministic, rule-based LLM stand-in (``LLM_PROVIDER=fake``): no network, never raises.

For offline development and end-to-end tests. It is NOT a language model: it only understands
the phrases below, and anything else becomes ``unclear``.

Supported phrases (case-insensitive)
------------------------------------
Create leave     "apply for annual leave from 2026-10-05 to 2026-10-07", "I need sick leave
                 tomorrow", "book a day off next monday", "vacation on 5 Oct"
Half day         "half day", "morning" (am), "afternoon" (pm). Single day: both parts equal.
                 Multi-day: "starting in the afternoon" -> start pm; "until the morning" -> end am.
                 "half day" without morning/afternoon -> ambiguity, parts left null.
Leave types      annual/vacation, sick/unwell/doctor/medical, personal/family/casual, unpaid/no pay
Dates            2026-10-05, today, tomorrow, yesterday, day after tomorrow,
                 [this|next] monday..sunday
                 ("next X" = first X strictly after today; "this X"/bare X = first X on or after
                 today), "5 Oct", "5th October", "Oct 5" (next occurrence; a lone "the 5th"
                 counts only when awaiting a date). Ranges: "from A to B", "A - B", "A until B".
                 One date = single day; "until B" or awaiting end_date sets the end only.
Create claim     "claim HKD 120 for taxi", "expense $120.50 lunch 2026-09-20", "reimburse 300
                 dollars for a keyboard"
Claim types      travel (taxi, flight, hotel, train, uber, mtr, bus, airfare), meal (lunch,
                 dinner, breakfast, meal), equipment (laptop, keyboard, mouse, monitor, headset,
                 equipment), training (course, training, certification, workshop, seminar,
                 exam), other
Amounts          "HKD 120", "HK$120", "$120.50" and "120 dollars" (all HKD), "120 hkd",
                 "120 HK dollars"; "USD 50", "US$50", "50 US dollars", "50 eur" keep their stated
                 currency; a bare number counts only when
                 awaiting the amount. The claim receipt date is the (first) date mentioned.
Provide details  when the context has an active form, draft or pending card and the message
                 carries fields (or no create verb): "make it sick leave", "the 5th", "HKD 200"
Status           "status", "my requests", "pending", "has my leave been approved", with optional
                 filters: leave|claim, "#12", pending/approved/rejected/cancelled/failed/draft
Balance          "how many annual leave days do I have left", "leave balance", "how much sick
                 leave do I have", "remaining leave", "my sick leave balance" (check_balance)
Cancel           "cancel #12", "withdraw my leave request 12", "cancel this"
Update           "change #12 to sick leave", "update request 12 end 2026-10-09", "move #12 to
                 next monday" (without an id and with an active draft -> provide_details)
Help             "hi", "hello", "help", "what can you do"
Out of scope     "approve ...", "reject ...", "decline ...", other people's data, weather, etc.
One-day reply    when the context awaits `end_date` and the current leave has a start date:
                 "yes", "just one day", "only that day", "same day", "one day only" ->
                 provide_details with leave.end_date = the current start date (a date in the
                 message sets that date instead)
Everything else  unclear

Attachments (no OCR)
--------------------
The fake provider cannot read images. A test fixture attachment is any file whose bytes contain
one line (a PDF comment line works: it stays a valid PDF)

    FAKE-DOC: {"doc_type": "sick_note", "rest_start_date": "2026-09-24",
               "rest_end_date": "2026-09-25", "person_name": "Amy Lau"}

(the real marker is a single line). The JSON holds ``DocumentExtraction`` fields: doc_type
(sick_note | receipt | other | unreadable, required), person_name, provider_name, issue_date,
rest_start_date, rest_end_date, days_advised, receipt_date, total_amount, currency,
suggested_claim_type, unreadable_fields, summary, confidence. Example receipt:

    FAKE-DOC: {"doc_type": "receipt", "total_amount": 88.5, "currency": "HKD",
               "receipt_date": "2026-09-20", "suggested_claim_type": "meal"}

- sick_note -> create_leave (provide_details if a leave draft exists), leave_type sick, dates =
  rest_start_date..rest_end_date. If only days_advised is given, end_date stays null and
  `rest_end_date` is added to the document's unreadable_fields and to ambiguities.
- receipt -> create_claim (provide_details if a claim draft exists) with total_amount as
  amount, currency, receipt_date and suggested_claim_type. Missing pieces go to
  unreadable_fields/ambiguities.
- A typed message is analysed too and its explicit values win over the document.
- No marker, malformed JSON, an unknown doc_type or a non-string payload -> doc_type
  unreadable (readable false); with no other intent the turn is `unclear`.
- One DocumentExtraction is returned per attachment, in order (``index`` = position).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import date, timedelta

from app.domain.enums import ClaimType, DayPart, LeaveType, RequestStatus, RequestType
from app.llm.schemas import (
    AgentTurn,
    AttachmentInput,
    ClaimFields,
    DocType,
    DocumentExtraction,
    Intent,
    LeaveFields,
    LLMContext,
    RequestRef,
    StatusQuery,
)

_MAX_CHARS = 2000

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4,
    "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}  # fmt: skip
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_WD_RE = "|".join(_WEEKDAYS)

_DATE_RE = re.compile(
    rf"""
    (?P<iso>\d{{4}}-\d{{2}}-\d{{2}})
    |(?P<dm>\b(?P<dm_d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<dm_m>{_MONTH_RE})\b)
    |(?P<md>\b(?P<md_m>{_MONTH_RE})\.?\s+(?P<md_d>\d{{1,2}})(?:st|nd|rd|th)?\b)
    |(?P<dat>\bday\s+after\s+tomorrow\b)
    |(?P<rel>\b(?P<rel_n>next|this)?\s*(?P<rel_w>{_WD_RE})\b)
    |(?P<word>\b(?P<word_w>today|tomorrow|yesterday)\b)
    |(?P<ord>\bthe\s+(?P<ord_d>\d{{1,2}})(?:st|nd|rd|th)\b)
    """,
    re.VERBOSE,
)
_ID_RE = re.compile(r"(?:#|\b(?:request|id|number|no\.?)\s*#?\s*)(\d{1,9})\b")
_CURRENCY_CODES = {"hkd", "usd", "eur", "gbp", "jpy", "cny", "rmb", "sgd", "aud", "cad"}
_AMOUNT_PRE = re.compile(
    r"(?<![\w.])(hkd\$|hk\$|us\$|\$|hkd|usd|eur|gbp|jpy|cny|rmb|sgd|aud|cad)\s*"
    r"(\d[\d,]*(?:\.\d+)?)"
)
_AMOUNT_POST = re.compile(
    r"(?<![\w.$])(\d[\d,]*(?:\.\d+)?)\s*(hkd\$|hk\$|hkd|usd|eur|gbp|jpy|cny|rmb|sgd|aud|cad"
    r"|us\s+dollars?|hk\s+dollars?|hong\s+kong\s+dollars?|dollars?|bucks)\b"
)
_BARE_NUMBER = re.compile(r"(?<![\w.#-])(\d[\d,]*(?:\.\d+)?)(?![\w-])")

_LEAVE_WORDS = re.compile(
    r"\b(leaves?|vacation|day\s*off|days\s*off|time\s*off|off\s+work|half[- ]?day|annual|sick|"
    r"unwell|ill)\b"
)
_CLAIM_WORDS = re.compile(
    r"\b(claims?|expenses?|reimburse\w*|receipts?|taxi|cab|uber|flight|hotel|lunch|dinner|"
    r"breakfast|laptop|keyboard|mouse|monitor|headset|course|certification)\b"
)
_CREATE_VERB = re.compile(
    r"\b(apply|applying|request|book|need|want|take|submit|create|file|make|new|would like|"
    r"i'd like|claim|reimburse\w*|going)\b"
)
_LEAVE_TYPES: list[tuple[LeaveType, re.Pattern[str]]] = [
    (LeaveType.UNPAID, re.compile(r"\b(unpaid|no[- ]pay)\b")),
    (LeaveType.SICK, re.compile(r"\b(sick|unwell|ill|doctor|medical)\b")),
    (LeaveType.PERSONAL, re.compile(r"\b(personal|family|casual)\b")),
    (LeaveType.ANNUAL, re.compile(r"\b(annual|vacation)\b")),
]
_CLAIM_TYPES: list[tuple[ClaimType, re.Pattern[str]]] = [
    (
        ClaimType.TRAVEL,
        re.compile(r"\b(taxi|cab|uber|flights?|hotel|train|mtr|bus|airfare|travel)\b"),
    ),
    (ClaimType.MEAL, re.compile(r"\b(lunch|dinner|breakfast|meals?|food)\b")),
    (
        ClaimType.EQUIPMENT,
        re.compile(r"\b(laptop|keyboard|mouse|monitor|headsets?|equipment|desk)\b"),
    ),
    (
        ClaimType.TRAINING,
        re.compile(r"\b(course|training|certification|workshop|seminar|exam)\b"),
    ),
    (ClaimType.OTHER, re.compile(r"\b(other|misc\w*)\b")),
]
_STATUS_WORDS = {
    RequestStatus.PENDING_APPROVAL: re.compile(r"\bpending\b"),
    RequestStatus.APPROVED: re.compile(r"\bapproved\b"),
    RequestStatus.REJECTED: re.compile(r"\brejected\b"),
    RequestStatus.CANCELLED: re.compile(r"\b(cancelled|canceled)\b"),
    RequestStatus.SUBMISSION_FAILED: re.compile(r"\b(failed|failure)\b"),
    RequestStatus.DRAFT: re.compile(r"\bdrafts?\b"),
}

_OUT_OF_SCOPE_ACTION = re.compile(r"\b(approve|reject|decline|deny)\b")
_OUT_OF_SCOPE_TOPIC = re.compile(
    r"\b(weather|joke|poem|recipe|payslip|password|someone else|colleague'?s?|"
    r"everyone'?s?|other employees?|his leave|her leave|their leave|ignore (?:your|all|the))\b"
)
_NEW_REQUEST = re.compile(
    r"\b(apply|applying|book|need|want|take|submit|create|file|new|would like|i'd like|going)\b"
)
_ONE_DAY = re.compile(
    r"^(yes|yep|yeah|yup|correct|ok|okay|sure)\b"
    r"|\b(just|only)\s+(one|1|a single)\s+day\b|\b(one|1)\s+day\s+only\b"
    r"|\b(only|just)\s+(that|the same)\s+day\b|\bsame\s+day\b|\bsingle\s+day\b"
)
_BALANCE = re.compile(
    r"\b(?:leave|annual|sick|vacation|holiday|pto)\s+(?:days?\s+)?(?:balances?|entitlements?)\b"
    r"|\b(?:my|the)\s+balances?\b"
    r"|\bhow\s+(?:many|much)\b[^?.!]*\b(?:leave|annual|sick|vacation|holiday|days?)\b"
    r"[^?.!]*\b(?:left|remain\w*|have|available|got|entitled|used)\b"
    r"|\b(?:remaining|leftover|unused)\s+(?:annual\s+|sick\s+)?(?:leave|days?|vacation)\b"
    r"|\b(?:leave|days?)\s+(?:i\s+have\s+)?(?:left|remaining)\b"
)
_CANCEL = re.compile(r"\b(cancel|withdraw|retract)\b")
_UPDATE = re.compile(
    r"\b(change|amend|edit|modify|reschedule)\b|\bupdate\s+(?:my|the|request|#|leave|claim)"
    r"|\bmove\s+(?:my|the|request|#|leave|claim)"
)
_STATUS = re.compile(
    r"\b(status|my requests?|my leaves?|my claims?|pending|any updates?|"
    r"(?:been|got)\s+(?:approved|rejected)|where is|how is|check on|show (?:me )?my|"
    r"(?:approved|rejected|cancelled|canceled|failed)\s+(?:requests?|leaves?|claims?))\b"
)
_HELP = re.compile(
    r"^\s*(hi|hello|hey|good (?:morning|afternoon|evening)|help|thanks|thank you|"
    r"what can you do|how does this work)\b"
)


def _mask(text: str, pattern: re.Pattern[str]) -> str:
    return pattern.sub(lambda m: " " * len(m.group(0)), text)


def _next_weekday(today: date, weekday: int, strictly_after: bool) -> date:
    delta = (weekday - today.weekday()) % 7
    if delta == 0 and strictly_after:
        delta = 7
    return today + timedelta(days=delta)


def _resolve_month_day(today: date, month: int, day: int) -> date | None:
    """Next occurrence (today or later) of a month/day, or None if it never exists."""
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate >= today:
            return candidate
    return None


def _day_in_month(today: date, day: int) -> date | None:
    """ "the 5th": that day this month if still ahead (or today), otherwise next month."""
    year, month = today.year, today.month
    for _ in range(2):
        try:
            candidate = date(year, month, day)
        except ValueError:
            candidate = None
        if candidate is not None and candidate >= today:
            return candidate
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return None


class _Parsed:
    """Everything the rules pull out of one message."""

    def __init__(self, raw: str, ctx: LLMContext) -> None:
        self.text = " ".join(raw[:_MAX_CHARS].lower().split())
        self.ctx = ctx
        self.ids = [int(m) for m in _ID_RE.findall(self.text)]
        self.dates: list[tuple[date, int]] = []  # (value, position)
        self.month_day_positions: set[int] = set()  # dates written without a year
        self.date_spans: list[tuple[int, int]] = []
        self._find_dates()

    def _find_dates(self) -> None:
        today = self.ctx.today
        awaiting_date = bool(self.ctx.awaiting and "date" in self.ctx.awaiting)
        for m in _DATE_RE.finditer(self.text):
            value: date | None = None
            yearless = False
            if m.group("iso"):
                try:
                    value = date.fromisoformat(m.group("iso"))
                except ValueError:
                    value = None
            elif m.group("dm"):
                value = _resolve_month_day(today, _MONTHS[m.group("dm_m")], int(m.group("dm_d")))
                yearless = True
            elif m.group("md"):
                value = _resolve_month_day(today, _MONTHS[m.group("md_m")], int(m.group("md_d")))
                yearless = True
            elif m.group("dat"):
                value = today + timedelta(days=2)
            elif m.group("rel"):
                weekday = _WEEKDAYS.index(m.group("rel_w"))
                value = _next_weekday(today, weekday, m.group("rel_n") == "next")
            elif m.group("word"):
                offset = {"today": 0, "tomorrow": 1, "yesterday": -1}[m.group("word_w")]
                value = today + timedelta(days=offset)
            elif m.group("ord") and awaiting_date:
                day = int(m.group("ord_d"))
                value = _day_in_month(today, day)
                yearless = True
            if value is not None:
                self.dates.append((value, m.start()))
                self.date_spans.append(m.span())
                if yearless:
                    self.month_day_positions.add(m.start())

    def preceding(self, position: int, width: int = 14) -> str:
        return self.text[max(0, position - width) : position]

    def masked(self) -> str:
        text = self.text
        for start, end in self.date_spans:
            text = text[:start] + " " * (end - start) + text[end:]
        return _mask(text, _ID_RE)


def _amount(parsed: _Parsed) -> tuple[float | None, str | None]:
    text = parsed.masked()
    best: tuple[int, float, str] | None = None
    for m in _AMOUNT_PRE.finditer(text):
        cur, num = m.group(1), m.group(2)
        best = (m.start(), float(num.replace(",", "")), _currency(cur))
        break
    if best is None:
        for m in _AMOUNT_POST.finditer(text):
            best = (m.start(), float(m.group(1).replace(",", "")), _currency(m.group(2)))
            break
    if best is None and parsed.ctx.awaiting == "amount":
        m = _BARE_NUMBER.search(text)
        if m:
            return float(m.group(1).replace(",", "")), None
    if best is None:
        return None, None
    return best[1], best[2]


def _currency(token: str) -> str:
    token = " ".join(token.split())
    if token in {"$", "hk$", "hkd$", "dollar", "dollars", "bucks"} or token.startswith(
        ("hk dollar", "hong kong dollar")
    ):
        return "HKD"
    if token == "us$" or token.startswith("us dollar"):
        return "USD"
    return token.upper() if token in _CURRENCY_CODES else "HKD"


def _first_type(text: str, table: list) -> object | None:
    for value, pattern in table:
        if pattern.search(text):
            return value
    return None


def _leave_fields(p: _Parsed) -> tuple[LeaveFields | None, list[str]]:
    ambiguities: list[str] = []
    fields: dict[str, object] = {}
    leave_type = _first_type(p.text, _LEAVE_TYPES)
    if leave_type is not None:
        fields["leave_type"] = leave_type
    current = p.ctx.current_leave
    dates = [d for d, _ in p.dates]
    awaiting = p.ctx.awaiting or ""
    if dates:
        first_pos = p.dates[0][1]
        until = bool(re.search(r"\b(until|till|through|thru|up to)\s*$", p.preceding(first_pos)))
        if len(dates) >= 2:
            fields["start_date"], fields["end_date"] = dates[0], dates[1]
        elif awaiting == "end_date" or until:
            fields["end_date"] = dates[0]
        elif awaiting == "start_date":
            fields["start_date"] = dates[0]
        elif current and current.start_date and not current.end_date:
            fields["end_date"] = dates[0]
        else:
            fields["start_date"] = fields["end_date"] = dates[0]
    _apply_day_parts(p, fields, ambiguities)
    if not fields:
        return None, ambiguities
    return LeaveFields.model_validate(fields), ambiguities


def _apply_day_parts(p: _Parsed, fields: dict[str, object], ambiguities: list[str]) -> None:
    text = p.text
    morning = bool(re.search(r"\bmorning\b", text)) and not re.search(r"good\s+morning", text)
    afternoon = bool(re.search(r"\bafternoon\b", text)) and not re.search(r"good\s+afternoon", text)
    half = bool(re.search(r"\bhalf[- ]?day\b", text))
    if not (morning or afternoon or half):
        return
    start, end = fields.get("start_date"), fields.get("end_date")
    single = (start is not None and start == end) or (start is None and end is None)
    if single:
        if morning and not afternoon:
            fields["start_day_part"] = fields["end_day_part"] = DayPart.AM
        elif afternoon and not morning:
            fields["start_day_part"] = fields["end_day_part"] = DayPart.PM
        else:
            ambiguities.append("Which half of the day: morning or afternoon?")
        return
    if re.search(r"\b(starting|start|from)\b[^,.;]*?\bafternoon\b", text):
        fields["start_day_part"] = DayPart.PM
    if re.search(r"\b(until|ending|end|to)\b[^,.;]*?\bmorning\b", text):
        fields["end_day_part"] = DayPart.AM
    if "start_day_part" not in fields and "end_day_part" not in fields:
        ambiguities.append("Which half days: start in the afternoon and/or end in the morning?")


def _claim_fields(p: _Parsed) -> ClaimFields | None:
    fields: dict[str, object] = {}
    claim_type = _first_type(p.text, _CLAIM_TYPES)
    if claim_type is not None:
        fields["claim_type"] = claim_type
    amount, currency = _amount(p)
    if amount is not None:
        fields["amount"] = amount
        if currency:
            fields["currency"] = currency
    if p.dates:
        receipt, position = p.dates[0]
        if position in p.month_day_positions and receipt > p.ctx.today:
            # "5 Sep" on a receipt means the most recent past occurrence, not next year's.
            try:
                receipt = receipt.replace(year=receipt.year - 1)
            except ValueError:
                pass
        fields["receipt_date"] = receipt
    return ClaimFields.model_validate(fields) if fields else None


def _type_hint(p: _Parsed) -> RequestType | None:
    leave, claim = bool(_LEAVE_WORDS.search(p.text)), bool(_CLAIM_WORDS.search(p.text))
    if leave and not claim:
        return RequestType.LEAVE
    if claim and not leave:
        return RequestType.CLAIM
    return None


def _turn(intent: Intent, rationale: str, confidence: float = 0.9, **kwargs: object) -> AgentTurn:
    return AgentTurn(
        intent=intent,
        rationale=rationale[:200],
        confidence=confidence,
        **kwargs,  # type: ignore[arg-type]
    )


def _unclear(reason: str = "no rule matched") -> AgentTurn:
    return _turn(
        Intent.UNCLEAR,
        f"fake rules: {reason}",
        0.2,
        followup_question=(
            "Sorry, I did not understand. I can help with a leave application or a staff claim."
        ),
    )


def _has_draft(ctx: LLMContext) -> bool:
    return bool(
        ctx.active_request_type
        or ctx.pending_card_action
        or ctx.current_leave
        or ctx.current_claim
        or ctx.editing_request_id
    )


def _fields_for(p: _Parsed, kind: RequestType | None) -> dict[str, object]:
    out: dict[str, object] = {}
    ambiguities: list[str] = []
    if kind is None:
        # Unknown form: money/claim words mean a claim, anything else (dates) a leave.
        claim = _claim_fields(p)
        kind = RequestType.CLAIM if claim and (claim.amount or claim.claim_type) else None
        kind = kind or RequestType.LEAVE
    if kind == RequestType.LEAVE:
        leave, ambiguities = _leave_fields(p)
        if leave is not None:
            out["leave"] = leave
    if kind == RequestType.CLAIM:
        claim = _claim_fields(p)
        if claim is not None:
            out["claim"] = claim
    if ambiguities:
        out["ambiguities"] = ambiguities
    return out


def _analyse(message: str, ctx: LLMContext) -> AgentTurn:
    p = _Parsed(message, ctx)
    text = p.text
    if not text:
        return _unclear("empty message")

    if _OUT_OF_SCOPE_ACTION.search(text) or _OUT_OF_SCOPE_TOPIC.search(text):
        return _turn(Intent.OUT_OF_SCOPE, "fake rules: approve/reject or unsupported topic")

    current = ctx.current_leave
    if (
        ctx.awaiting == "end_date"
        and current is not None
        and current.start_date is not None
        and not p.dates
        and _ONE_DAY.search(text)
    ):
        return _turn(
            Intent.PROVIDE_DETAILS,
            "fake rules: single-day answer",
            request_type=RequestType.LEAVE,
            leave=LeaveFields(end_date=current.start_date),
        )

    if _BALANCE.search(text) and not p.dates and not _CANCEL.search(text):
        return _turn(Intent.CHECK_BALANCE, "fake rules: leave balance question")

    hint = _type_hint(p)
    ref_id = p.ids[0] if p.ids else None

    if _CANCEL.search(text):
        target = RequestRef(request_id=ref_id, request_type=hint)
        return _turn(Intent.CANCEL_REQUEST, "fake rules: cancel keyword", target=target)

    if _UPDATE.search(text) and (ref_id is not None or not _has_draft(ctx)):
        kind = hint or ctx.active_request_type
        extra = _fields_for(p, kind)
        if kind is None:
            kind = (
                RequestType.LEAVE
                if "leave" in extra
                else RequestType.CLAIM
                if "claim" in extra
                else None
            )
        target = RequestRef(request_id=ref_id, request_type=kind)
        return _turn(
            Intent.UPDATE_REQUEST,
            "fake rules: update keyword",
            request_type=kind,
            target=target,
            **extra,
        )

    if _STATUS.search(text) and not _NEW_REQUEST.search(text):
        status = next((s for s, pat in _STATUS_WORDS.items() if pat.search(text)), None)
        query = StatusQuery(request_type=hint, request_id=ref_id, status=status)
        return _turn(Intent.CHECK_STATUS, "fake rules: status keyword", status_query=query)

    amount, _ = _amount(p)
    signals = bool(_LEAVE_WORDS.search(text) or _CLAIM_WORDS.search(text) or amount or p.dates)
    if _HELP.search(text) and not signals:
        return _turn(Intent.HELP, "fake rules: greeting or help")

    draft = _has_draft(ctx)
    create_verb = bool(_CREATE_VERB.search(text))
    active = ctx.active_request_type

    # A different form named with a create verb starts a new request even mid-draft.
    if hint and create_verb and (not draft or (active is not None and hint != active)):
        kind = hint
        intent = Intent.CREATE_LEAVE if kind == RequestType.LEAVE else Intent.CREATE_CLAIM
        return _turn(intent, "fake rules: create phrase", request_type=kind, **_fields_for(p, kind))

    if draft:
        kind = active or hint or (RequestType.CLAIM if ctx.current_claim else RequestType.LEAVE)
        extra = _fields_for(p, kind)
        if "leave" in extra or "claim" in extra:
            return _turn(
                Intent.PROVIDE_DETAILS, "fake rules: fields for current draft", request_type=kind,
                **extra,
            )  # fmt: skip
        return _unclear("draft context but no recognisable fields")

    if hint:
        intent = Intent.CREATE_LEAVE if hint == RequestType.LEAVE else Intent.CREATE_CLAIM
        return _turn(intent, "fake rules: type keyword", request_type=hint, **_fields_for(p, hint))
    if amount is not None:
        return _turn(
            Intent.CREATE_CLAIM, "fake rules: amount without draft",
            request_type=RequestType.CLAIM, **_fields_for(p, RequestType.CLAIM),
        )  # fmt: skip
    return _unclear()


_MARKER = b"FAKE-DOC:"
_MAX_MARKER_BYTES = 4000


def _read_document(index: int, attachment: object) -> DocumentExtraction:
    """Parse a ``FAKE-DOC:`` fixture line; anything invalid is an unreadable document."""
    unreadable = DocumentExtraction(index=index, doc_type=DocType.UNREADABLE, readable=False)
    try:
        data = attachment.data  # type: ignore[attr-defined]
        if not isinstance(data, bytes | bytearray):
            return unreadable
        start = data.find(_MARKER)
        if start < 0:
            return unreadable
        line = bytes(data[start + len(_MARKER) : start + len(_MARKER) + _MAX_MARKER_BYTES])
        line = line.split(b"\n", 1)[0].split(b"\r", 1)[0].strip()
        payload = json.loads(line.decode("utf-8", errors="strict"))
        if not isinstance(payload, dict):
            return unreadable
        payload["index"] = index
        doc = DocumentExtraction.model_validate(payload)
    except Exception:
        return unreadable
    if doc.doc_type == DocType.UNREADABLE:
        return doc.model_copy(update={"readable": False})
    return doc


def _first(*values: object) -> object:
    return next((v for v in values if v is not None), None)


def _apply_documents(
    text_turn: AgentTurn | None, docs: list[DocumentExtraction], ctx: LLMContext
) -> AgentTurn:
    """Fill intent/leave/claim from the documents the way the real model would."""
    sick = next((d for d in docs if d.readable and d.doc_type == DocType.SICK_NOTE), None)
    receipt = next((d for d in docs if d.readable and d.doc_type == DocType.RECEIPT), None)
    ambiguities: list[str] = list(text_turn.ambiguities) if text_turn else []
    followup: str | None = None
    if sick is None and receipt is None:
        if text_turn is not None and text_turn.intent not in (Intent.UNCLEAR, Intent.HELP):
            return text_turn.model_copy(update={"documents": docs})
        return _turn(
            Intent.UNCLEAR,
            "fake rules: no readable supported document",
            0.2,
            documents=docs,
            followup_question=(
                "I could not read the attachment. Please upload a clearer image or PDF, "
                "or tell me the details."
            ),
        )
    leave_first = receipt is None or (sick is not None and docs.index(sick) < docs.index(receipt))
    kind = RequestType.LEAVE if leave_first else RequestType.CLAIM
    if sick is not None and receipt is not None:
        ambiguities.append("Both a sick note and a receipt were attached; using the first.")
    typed = text_turn if text_turn is not None and text_turn.intent != Intent.UNCLEAR else None
    if kind == RequestType.LEAVE:
        assert sick is not None
        text_leave = typed.leave if typed and typed.leave else LeaveFields()
        leave = LeaveFields(
            leave_type=_first(text_leave.leave_type, LeaveType.SICK),  # type: ignore[arg-type]
            start_date=_first(text_leave.start_date, sick.rest_start_date),  # type: ignore[arg-type]
            end_date=_first(text_leave.end_date, sick.rest_end_date),  # type: ignore[arg-type]
            start_day_part=text_leave.start_day_part,
            end_day_part=text_leave.end_day_part,
        )
        if leave.end_date is None:
            if "rest_end_date" not in sick.unreadable_fields:
                sick.unreadable_fields.append("rest_end_date")
            ambiguities.append("The last day of the rest period could not be read.")
            followup = "What is the last day of your leave?"
        if leave.start_date is None:
            ambiguities.append("The first day of the rest period could not be read.")
            followup = "What is the first day of your leave?"
        intent = (
            Intent.PROVIDE_DETAILS
            if ctx.active_request_type == RequestType.LEAVE
            else Intent.CREATE_LEAVE
        )
        return _turn(
            intent,
            "fake rules: sick note document",
            request_type=RequestType.LEAVE,
            leave=leave,
            documents=docs,
            ambiguities=ambiguities[:5],
            followup_question=followup,
        )
    assert receipt is not None
    text_claim = typed.claim if typed and typed.claim else ClaimFields()
    claim = ClaimFields(
        claim_type=_first(text_claim.claim_type, receipt.suggested_claim_type),  # type: ignore[arg-type]
        amount=_first(text_claim.amount, receipt.total_amount),  # type: ignore[arg-type]
        currency=_first(text_claim.currency, receipt.currency),  # type: ignore[arg-type]
        receipt_date=_first(text_claim.receipt_date, receipt.receipt_date),  # type: ignore[arg-type]
    )
    if claim.amount is None:
        ambiguities.append("The total amount could not be read.")
        followup = "What is the total amount on the receipt?"
    elif claim.receipt_date is None:
        ambiguities.append("The receipt date could not be read.")
        followup = "What is the date on the receipt?"
    intent = (
        Intent.PROVIDE_DETAILS
        if ctx.active_request_type == RequestType.CLAIM
        else Intent.CREATE_CLAIM
    )
    return _turn(
        intent,
        "fake rules: receipt document",
        request_type=RequestType.CLAIM,
        claim=claim,
        documents=docs,
        ambiguities=ambiguities[:5],
        followup_question=followup,
    )


class FakeLLMProvider:
    """Rule-based provider. ``analyse`` never raises; unknown input yields ``unclear``."""

    name = "fake"
    model = "fake-rules-v1"

    def analyse(
        self,
        user_message: str,
        context: LLMContext,
        attachments: Sequence[AttachmentInput] = (),
    ) -> AgentTurn:
        try:
            message = user_message if isinstance(user_message, str) else ""
            if not attachments:
                return _analyse(message, context)
            docs = [_read_document(i, a) for i, a in enumerate(list(attachments)[:3])]
            text_turn = _analyse(message, context) if message.strip() else None
            return _apply_documents(text_turn, docs, context)
        except Exception:
            return _unclear("internal rule error")
