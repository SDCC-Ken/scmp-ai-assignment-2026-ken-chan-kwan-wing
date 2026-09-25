"""The chat turn as a LangGraph ``StateGraph`` (sync ``invoke``).

    load_context -> precheck -> understand -> documents -> route
        create_* / provide_details -> merge -> validate -> decide -> respond
        update_request            -> prepare_update -> merge -> validate -> decide -> respond
        cancel_request            -> prepare_cancel -> respond
        check_status              -> status -> respond
        help / out_of_scope / unclear -> explain -> respond

Only ``understand`` talks to the LLM (intent + fields, and the reading of attached documents).
``documents`` decides what the attachments are for (deterministic); ``merge`` folds a document
into the draft with the user's typed values winning. Every other node is deterministic
backend code: merging slots, Pydantic/policy validation, wording, cards, status lookups. Nodes
only READ the database; the chat service commits the results. Every node appends a
``TraceStep`` that the UI shows as the AI processing trace (no secrets, no e-mail address).
"""

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.chat import cards as card_builders
from app.chat import documents as docs
from app.chat.format import fmt_date, fmt_days
from app.chat.policy import (
    EDITABLE_STATUSES,
    FOLLOWUP_MAX_CHARS,
    LLM_MIN_CONFIDENCE,
    OPEN_REQUESTS_LIMIT,
    RETRYABLE_STATUSES,
    STATUS_LIST_LIMIT,
)
from app.chat.resolver import Unresolved, describe, not_editable_message, noun, resolve_target
from app.chat.state import (
    ClaimSlots,
    ConversationState,
    HeldDocument,
    LeaveSlots,
    PendingCard,
    dump_state,
    normalised_values,
    payload_hash,
)
from app.chat.text import looks_like_plain_sentence, other_emails, scrub
from app.chat.validation import (
    Missing,
    Problem,
    ValidLeave,
    coerce_enum,
    normalise_leave_slots,
    to_decimal,
    validate_claim,
    validate_leave,
)
from app.domain.enums import ClaimType, DayPart, LeaveType, RequestStatus, RequestType
from app.llm.base import LLMError, LLMOutputError, LLMProvider
from app.llm.schemas import (
    AgentTurn,
    ChatTurn,
    ClaimFields,
    DocumentExtraction,
    Intent,
    LeaveFields,
    LLMContext,
    RequestRef,
)
from app.llm.schemas import AttachmentInput as LLMAttachment
from app.schemas.chat import StatusCard, StatusItem, TraceStep, UiCard
from app.services.requests import (
    Req,
    brief,
    get_own_request,
    latest_external_reference,
    own_requests,
    request_values,
    slots_from_request,
    status_label,
    summary_text,
)

logger = logging.getLogger(__name__)

MUTATING = frozenset(
    {
        Intent.CREATE_LEAVE,
        Intent.CREATE_CLAIM,
        Intent.PROVIDE_DETAILS,
        Intent.UPDATE_REQUEST,
        Intent.CANCEL_REQUEST,
    }
)
AFFIRMATIVE = frozenset(
    {
        "yes",
        "y",
        "yep",
        "yeah",
        "yup",
        "ok",
        "okay",
        "sure",
        "confirm",
        "confirmed",
        "submit",
        "go ahead",
        "do it",
        "please do",
        "proceed",
        "sounds good",
        "looks good",
        "好",
        "好的",
        "係",
        "確認",
        "是",
    }
)
NEGATIVE = frozenset(["no", "n", "nope", "discard", "cancel", "never mind", "nevermind", "stop"])

_FIELD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "leave_type": ("type", "kind"),
    "start_date": ("start", "first day", "begin", "from", "when"),
    "end_date": ("end", "last day", "until", "through", "return", "back"),
    "claim_type": ("type", "kind", "category"),
    "amount": ("amount", "how much", "cost", "hkd", "total"),
    "receipt_date": ("receipt", "date", "when"),
}
_FIELD_QUESTIONS: dict[str, str] = {
    "leave_type": "Which type of leave is this: annual, sick, personal or unpaid?",
    "start_date": "What is the first day of your leave? For example 2026-10-05.",
    "end_date": (
        "What is the last day of your leave? If it is a single day, give me the same date again."
    ),
    "claim_type": "What type of claim is this: travel, meal, equipment, training or other?",
    "amount": "How much is the claim, in HKD?",
    "receipt_date": "What is the date on the receipt?",
}
# Words (lowercase) that name a slot inside an LLM ambiguity string.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "leave_type": ("leave_type", "leave type", "type of leave"),
    "start_date": ("start_date", "start date", "start", "first day", "begin", "from"),
    "end_date": ("end_date", "end date", "end", "last day", "until", "through", "return"),
    "start_day_part": ("start_day_part", "half", "morning", "afternoon", "am", "pm", "day part"),
    "end_day_part": ("end_day_part", "half", "morning", "afternoon", "am", "pm", "day part"),
    "claim_type": ("claim_type", "claim type", "type of claim", "category"),
    "amount": ("amount", "cost", "price", "how much", "total"),
    "currency": ("currency", "hkd", "usd", "dollar"),
    "receipt_date": ("receipt_date", "receipt date", "receipt"),
}
_GENERIC_DATE_FIELDS: dict[RequestType, tuple[str, ...]] = {
    RequestType.LEAVE: ("start_date", "end_date"),
    RequestType.CLAIM: ("receipt_date",),
}

# Intents a document may drive (fill a draft); anything else ignores the attachments.
DOC_INTENTS = frozenset(
    {
        Intent.CREATE_LEAVE,
        Intent.CREATE_CLAIM,
        Intent.PROVIDE_DETAILS,
        Intent.UNCLEAR,
        Intent.UPDATE_REQUEST,
    }
)
_CREATE_KIND = {Intent.CREATE_LEAVE: RequestType.LEAVE, Intent.CREATE_CLAIM: RequestType.CLAIM}

_ONE_DAY_RE = re.compile(
    r"^(yes|yep|yeah|just one day|just 1 day|one day|one day only|1 day|1 day only|"
    r"only that day|only one day|just that day|that day only|that day|single day|same day)$"
)


def _is_one_day_reply(message: str) -> bool:
    """A short "just one day" answer to the single-date question (any case, punctuation)."""
    text = re.sub(r"[^\w\s]", " ", message.lower())
    return _ONE_DAY_RE.match(" ".join(text.split())) is not None


def _awaiting_end_date(conv: ConversationState) -> bool:
    return (
        conv.awaiting == "end_date"
        and conv.active_request_type == RequestType.LEAVE
        and conv.leave.start_date is not None
        and conv.leave.end_date is None
        and conv.open_card() is None
    )


HELP_TEXT = (
    "I can help you with two things: leave applications (annual, sick, personal or unpaid) and "
    "staff claims (travel, meal, equipment, training or other). I can create a request, change "
    "or cancel one that has not been reviewed yet, and tell you the status of your own requests. "
    "Approvals are done by the HR and Finance approvers, not through this chat. Try: "
    '"I\'d like annual leave from 2026-10-05 to 2026-10-07" or "Claim HKD 120 for a taxi '
    'receipt from yesterday".'
)
OUT_OF_SCOPE_TEXT = (
    "I can only help with your own leave applications and staff claims: creating, changing, "
    "cancelling and checking the status of your requests. I can't approve or reject anything "
    "(HR and Finance approvers do that in their own screens), I can't act for other people and "
    "I can't share anyone else's data."
)
UNCLEAR_TEXT = (
    "I'm not sure what you would like to do. I can create a leave application or a staff claim, "
    "change or cancel one of your pending requests, or show the status of your requests. "
    "What would you like?"
)
OTHER_USER_TEXT = (
    "I can only act for the signed-in user, which is you. I can't create, change or cancel "
    "requests on someone else's behalf, and I ignore other people's e-mail addresses in "
    "messages. Nothing was changed."
)


# --- data passed through the graph ------------------------------------------------------------
@dataclass
class TurnDeps:
    session: Session
    llm: LLMProvider
    user_id: int
    user_email: str
    user_name: str
    today: date


@dataclass
class Reply:
    text: str
    ui: UiCard | None = None
    warning_code: str | None = None


@dataclass
class TurnResult:
    reply: Reply
    state: ConversationState
    trace: list[TraceStep]
    superseded: list[str] = field(default_factory=list)
    state_changed: bool = False
    # What the provider read from each attachment of this turn: ``{attachment_id: extraction}``
    # (only DocumentExtraction fields); the chat service stores it in ``extraction_json``.
    extractions: dict[int, dict[str, Any]] = field(default_factory=dict)


class TurnState(TypedDict, total=False):
    deps: TurnDeps
    message: str
    conv: ConversationState
    before: dict[str, Any]
    history: list[ChatTurn]
    ctx: LLMContext
    turn: AgentTurn
    trace: list[TraceStep]
    notices: list[str]
    superseded: list[str]
    outcome: Any
    reply: Reply | None
    error: str | None
    other_emails: list[str]
    mode: str | None
    forced_target: tuple[RequestType, int] | None
    doc_run: docs.DocRun | None
    doc_intro: str | None
    extractions: dict[int, dict[str, Any]]
    served_by: str | None
    llm_ms: int
    result: TurnResult


# --- helpers ------------------------------------------------------------------------------------
def _trace(
    state: TurnState,
    step: str,
    label: str,
    detail: str = "",
    *,
    ok: bool = True,
    started: float | None = None,
) -> list[TraceStep]:
    elapsed = 0 if started is None else int((time.perf_counter() - started) * 1000)
    steps = list(state.get("trace", []))
    steps.append(
        TraceStep(step=step, label=label, detail=detail, ok=ok, duration_ms=elapsed)  # type: ignore[arg-type]
    )
    return steps


def _join(notices: list[str], text: str) -> str:
    return " ".join([*notices, text]) if notices else text


def _with_notices(state: TurnState, text: str) -> str:
    return _join(state.get("notices") or [], text)


def _leave_fields_of(slots: LeaveSlots) -> LeaveFields:
    return LeaveFields(**slots.model_dump())


def _claim_fields_of(slots: ClaimSlots) -> ClaimFields:
    data = slots.model_dump()
    data["amount"] = (
        float(slots.amount) if slots.amount is not None and slots.amount.is_finite() else None
    )
    return ClaimFields(**data)


def _has_values(fields: LeaveFields | ClaimFields | None) -> bool:
    return fields is not None and any(v is not None for v in fields.model_dump().values())


def _snapshot(conv: ConversationState) -> dict[str, Any]:
    return {
        "type": conv.active_request_type,
        "editing": conv.editing_request_id,
        "leave": normalised_values(conv, RequestType.LEAVE),
        "claim": normalised_values(conv, RequestType.CLAIM),
        "attachments": list(conv.attachment_ids),
        "sources": dict(conv.sources),
    }


def _ambiguous_fields(ambiguities: list[str], request_type: RequestType) -> set[str] | None:
    """Slot names the LLM flagged as unsure; ``None`` = it named none, so hold back ALL fields."""
    if not ambiguities:
        return set()
    text = " ".join(ambiguities).lower().replace("_", " ")
    names = (
        ("leave_type", "start_date", "end_date", "start_day_part", "end_day_part")
        if request_type == RequestType.LEAVE
        else ("claim_type", "amount", "currency", "receipt_date")
    )

    def mentioned(alias: str) -> bool:
        return re.search(rf"\b{re.escape(alias.replace('_', ' '))}\b", text) is not None

    found = {name for name in names if any(mentioned(a) for a in _FIELD_ALIASES[name])}
    date_fields = set(_GENERIC_DATE_FIELDS[request_type])
    if not found & date_fields and re.search(r"\bdates?\b", text):
        found |= date_fields  # "the date is unclear" without saying which one
    return found or None


def _draft_label(conv: ConversationState) -> str:
    if conv.editing_request_id is not None and conv.active_request_type:
        return f"your changes to {noun(conv.active_request_type)} #{conv.editing_request_id}"
    if conv.active_request_type:
        kind = "leave application" if conv.active_request_type == RequestType.LEAVE else "claim"
        return f"your unfinished {kind}"
    return "your unfinished draft"


def _supersede_open_card(conv: ConversationState, superseded: list[str]) -> list[str]:
    card = conv.open_card()
    if card is None:
        return superseded
    card.state = "superseded"
    conv.pending_card = None
    return [*superseded, card.card_id]


def _wording_ok(text: str | None, field_name: str) -> str | None:
    """LLM wording is used only for a plain missing-field question about the right field."""
    if text is None or not looks_like_plain_sentence(text.strip(), FOLLOWUP_MAX_CHARS):
        return None
    low = text.lower()
    if not any(k in low for k in _FIELD_KEYWORDS.get(field_name, ())):
        return None
    return text.strip()


# --- nodes ---------------------------------------------------------------------------------------
def load_context(state: TurnState) -> dict[str, Any]:
    started = time.perf_counter()
    deps, conv = state["deps"], state["conv"]
    open_requests = [
        brief(r)
        for r in own_requests(
            deps.session, deps.user_id, statuses=set(EDITABLE_STATUSES), limit=OPEN_REQUESTS_LIMIT
        )
    ]
    card = conv.open_card()
    ctx = LLMContext(
        today=deps.today,
        weekday=deps.today.strftime("%A"),
        user_display_name=deps.user_name,
        active_request_type=conv.active_request_type,
        current_leave=_leave_fields_of(conv.leave) if not conv.leave.is_empty() else None,
        current_claim=_claim_fields_of(conv.claim) if not conv.claim.is_empty() else None,
        editing_request_id=conv.editing_request_id,
        pending_card_action=card.action if card else None,
        awaiting=conv.awaiting,
        recent_messages=state.get("history", []),
        open_requests=open_requests,
    )
    detail = (
        f"{len(state.get('history', []))} recent messages, {len(open_requests)} open requests"
        + (f", open card: {card.action}" if card else "")
    )
    return {
        "ctx": ctx,
        "trace": _trace(
            state, "understand", "Loaded conversation context", detail, started=started
        ),
    }


def route_precheck(state: TurnState) -> str:
    card = state["conv"].open_card()
    if card is None or _turn_attachments(state["deps"]):
        return "understand"  # a message with files is never a bare "yes" / "no"
    text = state["message"].strip().lower().strip(" .!?~。！")
    if text in AFFIRMATIVE:
        return "remind_yes"
    if text in NEGATIVE:
        return "remind_no"
    return "understand"


def remind(state: TurnState) -> dict[str, Any]:
    """A bare "yes"/"no" never confirms anything: only the card buttons do."""
    started = time.perf_counter()
    card = state["conv"].open_card()
    assert card is not None
    label = card_builders.CONFIRM_LABELS[card.action]
    if state["message"].strip().lower().strip(" .!?~。！") in NEGATIVE:
        text = (
            "I only act when you press a button on the card. To drop it, press Discard on the "
            "card above, or tell me what you would like to change instead."
        )
    else:
        text = (
            f'To keep you in control I only go ahead when you press the "{label}" button on '
            "the card above. Typing yes doesn't do it. You can also tell me what to change."
        )
    return {
        "reply": Reply(text),
        "trace": _trace(
            state, "decide", "Waiting for the card button", "no action taken", started=started
        ),
    }


def _turn_attachments(deps: TurnDeps) -> list[Any]:
    """The uploaded files of this message (``ChatTurnDeps.attachments``; none for a plain turn)."""
    return list(getattr(deps, "attachments", None) or [])


def understand(state: TurnState) -> dict[str, Any]:
    started = time.perf_counter()
    deps = state["deps"]
    files = _turn_attachments(deps)
    sent = [f for f in files if f.data is not None]
    typed = state["message"].strip()
    if files and not sent and not typed:
        return {
            "error": "attachment_unreadable",
            "trace": _trace(
                state,
                "understand",
                "Could not open the attachment",
                "the stored file is missing or unreadable",
                ok=False,
                started=started,
            ),
        }
    try:
        if sent:
            inputs = [
                LLMAttachment(
                    id=f.id, filename=f.filename, content_type=f.content_type, data=f.data
                )
                for f in sent
            ]
            turn = deps.llm.analyse(typed or docs.NEUTRAL_MESSAGE, state["ctx"], inputs)
        else:
            turn = deps.llm.analyse(
                state["message"] if typed else docs.NEUTRAL_MESSAGE, state["ctx"]
            )
    except LLMOutputError:
        logger.warning("LLM returned invalid structured output")
        return {
            "error": "llm_invalid_output",
            "trace": _trace(
                state,
                "understand",
                "Intent detection failed",
                "the AI service returned an unusable answer",
                ok=False,
                started=started,
            ),
        }
    except LLMError:
        logger.warning("LLM provider unavailable")
        return {
            "error": "llm_unavailable",
            "trace": _trace(
                state,
                "understand",
                "Intent detection failed",
                "the AI service is unavailable",
                ok=False,
                started=started,
            ),
        }
    except Exception:
        logger.exception("Unexpected error in the LLM provider")
        return {
            "error": "llm_unavailable",
            "trace": _trace(
                state,
                "understand",
                "Intent detection failed",
                "unexpected provider error",
                ok=False,
                started=started,
            ),
        }
    llm_ms = int((time.perf_counter() - started) * 1000)
    served = getattr(deps.llm, "last_served_by", None)
    conf = "n/a" if turn.confidence is None else f"{turn.confidence:.2f}"
    detail = f"{turn.intent.value} (confidence {conf})"
    if (
        _awaiting_end_date(state["conv"])
        and _is_one_day_reply(state["message"])
        and turn.intent not in (Intent.UPDATE_REQUEST, Intent.CANCEL_REQUEST)
    ):
        turn = turn.model_copy(update={"intent": Intent.PROVIDE_DETAILS, "confidence": None})
        detail += '; read as "just one day"'
    if turn.rationale and not files:  # with documents the rationale could carry names from them
        detail += f" - {scrub(turn.rationale, 160)}"
    return {
        "turn": turn,
        "other_emails": other_emails(state["message"], deps.user_email),
        "served_by": served if isinstance(served, str) else None,
        "llm_ms": llm_ms,
        "trace": _trace(state, "understand", "Intent detected", detail, started=started),
    }


def route_after_understand(state: TurnState) -> str:
    return "error" if state.get("error") else "documents"


def route_after_documents(state: TurnState) -> str:
    return "respond" if state.get("reply") is not None else route_understand(state)


def route_understand(state: TurnState) -> str:
    if state.get("error"):
        return "error"
    turn = state["turn"]
    conv = state["conv"]
    intent = turn.intent
    if intent in MUTATING:
        if state.get("other_emails"):
            return "refuse"
        if turn.confidence is not None and turn.confidence < LLM_MIN_CONFIDENCE:
            return "clarify"
    if intent == Intent.PROVIDE_DETAILS:
        card = conv.open_card()
        if card is not None and card.request_id is not None and conv.editing_request_id is None:
            if card.action == "retry":
                return "prepare_update"  # editing the failed request starts an update
            if card.action == "cancel":
                return "hold_cancel"
    if intent == Intent.UNCLEAR and conv.active_request_type and conv.awaiting in _FIELD_QUESTIONS:
        if conv.open_card() is None:
            return "merge"  # a reply we could not read while a question is open: ask it again
    if intent in (Intent.CREATE_LEAVE, Intent.CREATE_CLAIM, Intent.PROVIDE_DETAILS):
        return "merge"
    if intent == Intent.UPDATE_REQUEST:
        return "prepare_update"
    if intent == Intent.CANCEL_REQUEST:
        return "prepare_cancel"
    if intent == Intent.CHECK_STATUS:
        return "status"
    return "explain"


def _document_trace(state: TurnState, infos: list[docs.DocInfo]) -> list[TraceStep]:
    """The ``documents`` step: types and readability only (no names, values or file names)."""
    label, ok = docs.trace_label(infos)
    served = state.get("served_by")
    detail = f"answered by {scrub(served, 100)}" if served else ""
    steps = list(state.get("trace", []))
    steps.append(
        TraceStep(
            step="documents", label=label, detail=detail, ok=ok, duration_ms=state.get("llm_ms", 0)
        )
    )
    return steps


def _held_document_turn(state: TurnState) -> dict[str, Any]:
    """No new file: the user may be answering "which one do you want?" about a held document."""
    turn, conv = state["turn"], state["conv"]
    held = conv.held_document
    assert held is not None
    choice = _CREATE_KIND.get(turn.intent)
    if choice is None and turn.intent in (Intent.UNCLEAR, Intent.PROVIDE_DETAILS):
        choice = docs.kind_from_text(state["message"])
    try:
        extraction = DocumentExtraction.model_validate(held.extraction)
    except ValueError:
        conv.held_document = None
        return {"conv": conv}
    info = docs.DocInfo(held.attachment_id, held.filename, extraction)
    if choice is not None and choice == info.kind:
        started = time.perf_counter()
        conv.held_document = None
        new_turn = turn.model_copy(
            update={
                "intent": Intent.CREATE_LEAVE
                if choice == RequestType.LEAVE
                else Intent.CREATE_CLAIM,
                "request_type": choice,
                "confidence": None,
                "ambiguities": [],
            }
        )
        steps = _trace(
            state,
            "documents",
            "Used the document you sent earlier",
            info.label,
            ok=True,
            started=started,
        )
        return {
            "conv": conv,
            "turn": new_turn,
            "doc_run": docs.DocRun([info], info),
            "trace": steps,
        }
    if choice is not None or turn.intent == Intent.PROVIDE_DETAILS:
        conv.held_document = None  # they carry on with the open draft: forget the held file
        return {"conv": conv}
    return {}


def documents(state: TurnState) -> dict[str, Any]:
    """Decide what this message's attachments are for. Deterministic: the provider only READ them
    (``turn.documents``); nothing said inside a document is ever acted on."""
    started = time.perf_counter()
    deps, conv, turn = state["deps"], state["conv"], state["turn"]
    files = _turn_attachments(deps)
    if not files:
        return _held_document_turn(state) if conv.held_document is not None else {}

    infos = docs.pair_documents(files, turn.documents)
    conv.held_document = None  # a new upload replaces any file that was waiting for an answer
    extractions = {
        i.attachment_id: i.extraction.model_dump(mode="json") for i in infos if i.extraction
    }
    out: dict[str, Any] = {
        "conv": conv,
        "extractions": extractions,
        "trace": _document_trace(state, infos),
    }
    if turn.intent not in DOC_INTENTS:
        return out  # e.g. a status question or "cancel": the files are not used
    typed_text = state["message"].strip()
    primary = next((i for i in infos if i.kind is not None), None)

    if primary is None:
        if turn.intent == Intent.UNCLEAR or not typed_text:
            names = ", ".join(i.name for i in infos)
            if any(not i.readable for i in infos):
                text = (
                    f"I could not read {names}. Please type the details (for a leave: type and "
                    "dates; for a claim: amount and receipt date), or upload a clearer image "
                    "or PDF."
                )
            else:
                text = (
                    f"I can see {names}, but it does not look like a sick note or a receipt, so "
                    "I can't fill a request from it. Is it for a leave or a claim? You can also "
                    "type the details."
                )
            out["reply"] = Reply(_with_notices(state, text))
            out["trace"] = _trace(
                {**state, "trace": out["trace"]},
                "decide",
                "Asked for the details in text",
                "nothing could be read from the attachment",
                started=started,
            )
            return out
        out["doc_run"] = docs.DocRun(infos, None)
        return out

    kind = primary.kind
    assert kind is not None and primary.extraction is not None
    active = conv.active_request_type
    if (
        turn.intent != Intent.UPDATE_REQUEST
        and active is not None
        and active != kind
        and (conv.has_draft() or conv.open_card() is not None)
    ):
        # A receipt during a leave draft (or the reverse): never mix; ask which one is meant.
        conv.held_document = HeldDocument(
            attachment_id=primary.attachment_id,
            filename=primary.filename,
            extraction=primary.extraction.model_dump(mode="json"),
        )
        want = "leave application" if kind == RequestType.LEAVE else "claim"
        text = (
            f"You have {_draft_label(conv)} open, and {primary.name} looks like "
            f'{docs.kind_text(kind)}. I don\'t want to mix the two. Reply "{kind.value}" to '
            f"start a new {want} from it (this puts your open draft aside), or just carry on "
            "with what you have."
        )
        out["reply"] = Reply(_with_notices(state, text))
        out["trace"] = _trace(
            {**state, "trace": out["trace"]},
            "decide",
            "Asked which request the document is for",
            "the document does not match the open draft",
            started=started,
        )
        return out

    if turn.intent in (Intent.UNCLEAR, Intent.PROVIDE_DETAILS) and turn.request_type in (
        None,
        kind,
    ):
        same_draft = active == kind and conv.has_draft()
        new_intent = (
            Intent.PROVIDE_DETAILS
            if same_draft
            else (Intent.CREATE_LEAVE if kind == RequestType.LEAVE else Intent.CREATE_CLAIM)
        )
        confidence = turn.confidence
        if turn.intent == Intent.UNCLEAR:
            confidence = primary.extraction.confidence
        out["turn"] = turn.model_copy(
            update={"intent": new_intent, "request_type": kind, "confidence": confidence}
        )
    out["doc_run"] = docs.DocRun(infos, primary)
    return out


def error_reply(state: TurnState) -> dict[str, Any]:
    code = state["error"]
    has_files = bool(_turn_attachments(state["deps"]))
    if code == "attachment_unreadable":
        return {
            "reply": Reply(
                "I couldn't open the file you sent, so nothing was changed. Please upload it "
                "again, or type the details and I will fill the request from those."
            )
        }
    if code == "llm_invalid_output":
        text = (
            "I couldn't make sense of the AI service's answer, so nothing was changed. "
            "Please try again, or rephrase your message."
        )
    else:
        text = (
            "I couldn't reach the AI service just now, so nothing was changed. "
            "Please try again in a moment."
        )
    if has_files:
        text = (
            "I couldn't read your attachment just now because the AI service did not give a "
            "usable answer, so nothing was changed. Please type the details (for a leave: type "
            "and dates; for a claim: amount and receipt date) or try uploading the file again."
        )
    return {"reply": Reply(text, warning_code=code)}


def refuse_other_user(state: TurnState) -> dict[str, Any]:
    started = time.perf_counter()
    return {
        "reply": Reply(OTHER_USER_TEXT),
        "trace": _trace(
            state,
            "validate",
            "Signed-in user check",
            "message names another e-mail address; refused, nothing changed",
            ok=False,
            started=started,
        ),
    }


def clarify_low_confidence(state: TurnState) -> dict[str, Any]:
    started = time.perf_counter()
    return {
        "reply": Reply(
            "I'm not sure I understood that correctly, so I haven't changed anything. "
            "Could you say it again with a little more detail (what you want to do and the "
            "dates or amount)?"
        ),
        "trace": _trace(
            state,
            "decide",
            "Asked for clarification",
            "confidence below threshold; no card shown",
            started=started,
        ),
    }


def hold_cancel(state: TurnState) -> dict[str, Any]:
    started = time.perf_counter()
    card = state["conv"].open_card()
    assert card is not None
    return {
        "reply": Reply(
            f"There is a cancellation card waiting for {noun(card.request_type)} "
            f'#{card.request_id}. Press "Cancel request" to cancel it, or Discard to keep it.'
        ),
        "trace": _trace(
            state, "decide", "Cancellation card still open", "no change", started=started
        ),
    }


def explain(state: TurnState) -> dict[str, Any]:
    started = time.perf_counter()
    intent = state["turn"].intent
    text = {Intent.HELP: HELP_TEXT, Intent.OUT_OF_SCOPE: OUT_OF_SCOPE_TEXT}.get(
        intent, UNCLEAR_TEXT
    )
    if state["conv"].open_card() is not None:
        text += " (You still have a card above waiting for your decision.)"
    return {
        "reply": Reply(text),
        "trace": _trace(state, "decide", "Explained what I can do", intent.value, started=started),
    }


# -- status ---------------------------------------------------------------------------------------
def _status_item(session: Session, req: Req) -> StatusItem:
    return StatusItem(
        request_type=req.request_type,
        id=req.id,
        status=req.status.value,
        status_label=status_label(req.status),
        summary=summary_text(req),
        submitted_at=req.submitted_at,
        reviewed_at=req.reviewed_at,
        reviewer_note=req.reviewer_note,
        external_reference_id=latest_external_reference(session, req),
    )


def status(state: TurnState) -> dict[str, Any]:
    started = time.perf_counter()
    deps, turn = state["deps"], state["turn"]
    query = turn.status_query
    rtype = (query.request_type if query else None) or turn.request_type
    rid = query.request_id if query else None
    wanted = query.status if query else None
    rows = own_requests(
        deps.session,
        deps.user_id,
        request_type=rtype,
        request_id=rid,
        statuses={wanted} if wanted else None,
        limit=STATUS_LIST_LIMIT,
    )
    kind = {"leave": "leave requests", "claim": "claims"}.get(
        rtype.value if rtype else "", "requests"
    )
    if not rows:
        if rid is not None:
            text = (
                f"I couldn't find a request with id {rid} among your requests. "
                "Ask me to show your requests to see their ids."
            )
        else:
            suffix = f" with status {status_label(wanted)}" if wanted else ""
            text = f"You don't have any {kind}{suffix}."
        ui: UiCard = StatusCard(requests=[], empty=True)
    else:
        items = [_status_item(deps.session, r) for r in rows]
        lines = []
        for r, item in zip(rows, items, strict=True):
            line = f"#{r.id} {item.summary} - {item.status_label}"
            if r.status == RequestStatus.REJECTED and r.reviewer_note:
                line += f" (reviewer note: {r.reviewer_note})"
            lines.append(line)
        if len(rows) == 1:
            head = "Here is that request."
        else:
            head = f"Here are your {len(rows)} most recent {kind}."
        text = head + " " + " | ".join(lines)
        ui = StatusCard(requests=items, empty=False)
    return {
        "reply": Reply(text, ui=ui),
        "trace": _trace(
            state,
            "status",
            "Looked up your requests",
            f"{len(rows)} found (own requests only)",
            started=started,
        ),
    }


# -- merge -------------------------------------------------------------------------------------
def _apply_leave(
    conv: ConversationState, fields: LeaveFields, skip: set[str] | None, notices: list[str]
) -> list[str]:
    changed: list[str] = []
    if skip is None:
        return changed
    for name in ("leave_type", "start_date", "end_date", "start_day_part", "end_day_part"):
        value = getattr(fields, name)
        if value is None or name in skip:
            continue
        if name == "leave_type":
            coerced = coerce_enum(LeaveType, value)
            if coerced is None:
                notices.append(
                    f'I don\'t offer "{scrub(str(value), 40)}" as a leave type: the types are '
                    "annual, sick, personal and unpaid."
                )
                continue
            value = coerced
        elif name.endswith("day_part"):
            coerced_part = coerce_enum(DayPart, value)
            if coerced_part is None:
                continue
            value = coerced_part
        setattr(conv.leave, name, value)
        changed.append(name)
    return changed


def _apply_claim(
    conv: ConversationState, fields: ClaimFields, skip: set[str] | None, notices: list[str]
) -> list[str]:
    changed: list[str] = []
    if skip is None:
        return changed
    for name in ("claim_type", "amount", "currency", "receipt_date"):
        value = getattr(fields, name)
        if value is None or name in skip:
            continue
        if name == "claim_type":
            coerced = coerce_enum(ClaimType, value)
            if coerced is None:
                notices.append(
                    f'I don\'t offer "{scrub(str(value), 40)}" as a claim type: the types are '
                    "travel, meal, equipment, training and other."
                )
                continue
            value = coerced
        elif name == "amount":
            dec = to_decimal(value)
            if dec is None:
                notices.append("I couldn't read that amount as a number.")
                continue
            value = dec
        elif name == "currency":
            value = str(value).strip().upper()
        setattr(conv.claim, name, value)
        changed.append(name)
    return changed


def _track_document_fields(
    state: TurnState,
    conv: ConversationState,
    rtype: RequestType,
    before: dict[str, Any],
    set_fields: list[str],
    effects: docs.DocEffects | None,
    notices: list[str],
) -> None:
    """Keep the draft's document bookkeeping in step with the fields that were just set."""
    sourced = effects.sourced if effects else set()
    now = normalised_values(conv, rtype)
    old = before["leave" if rtype == RequestType.LEAVE else "claim"]
    for name in set_fields:
        conv.doc_unread.pop(name, None)  # the missing value has been supplied
        if name in sourced and effects and effects.primary_id is not None:
            conv.sources[name] = effects.primary_id
        elif old.get(name) != now.get(name):
            conv.sources.pop(name, None)  # the user replaced a document value
    if effects is None:
        return
    conv.doc_conflicts.update(effects.conflicts)
    conv.doc_unread.update(effects.unread)
    if effects.days_advised is not None:
        conv.doc_days_advised = effects.days_advised
    for warning in effects.warnings:
        if warning not in conv.doc_warnings:
            conv.doc_warnings.append(warning)
    docs.cap_attachments(state["deps"].session, conv, rtype, effects.attachment_ids, notices)


def merge(state: TurnState) -> dict[str, Any]:
    started = time.perf_counter()
    turn, conv = state["turn"], state["conv"]
    notices = list(state.get("notices", []))
    superseded = list(state.get("superseded", []))
    before = _snapshot(conv)
    update_mode = state.get("mode") == "update"
    has_leave, has_claim = _has_values(turn.leave), _has_values(turn.claim)

    if update_mode:
        rtype = conv.active_request_type
    else:
        if turn.intent == Intent.CREATE_LEAVE:
            rtype = RequestType.LEAVE
        elif turn.intent == Intent.CREATE_CLAIM:
            rtype = RequestType.CLAIM
        elif turn.request_type is not None:
            rtype = turn.request_type
        elif has_leave and not has_claim:
            rtype = RequestType.LEAVE
        elif has_claim and not has_leave:
            rtype = RequestType.CLAIM
        else:
            rtype = conv.active_request_type or (RequestType.LEAVE if has_leave else None)
    if rtype is None:
        conv.awaiting = "request_type"
        return {
            "reply": Reply(
                "Is this for a leave application or a staff claim? Tell me which one and give "
                "me the details you have."
            ),
            "trace": _trace(
                state,
                "merge",
                "No form to fill yet",
                "asked whether it is a leave or a claim",
                started=started,
            ),
        }

    if has_leave and has_claim and not update_mode:
        other = "claim" if rtype == RequestType.LEAVE else "leave application"
        first = "leave application" if rtype == RequestType.LEAVE else "claim"
        notices.append(
            f"You mentioned both a leave and a claim. I'll do the {first} first; tell me about "
            f"the {other} once this one is done."
        )

    if not update_mode:
        fresh = (
            turn.intent in (Intent.CREATE_LEAVE, Intent.CREATE_CLAIM)
            or conv.active_request_type != rtype
        )
        if fresh:
            if conv.has_draft() and (
                conv.active_request_type not in (None, rtype) or conv.editing_request_id is not None
            ):
                notices.append(f"I set aside {_draft_label(conv)}.")
            conv.reset_draft()
            conv.active_request_type = rtype

    typed_fields: LeaveFields | ClaimFields = (
        (turn.leave or LeaveFields())
        if rtype == RequestType.LEAVE
        else (turn.claim or ClaimFields())
    )
    effects: docs.DocEffects | None = None
    doc_intro: str | None = None
    run = state.get("doc_run")
    if run is not None:
        effects = docs.apply_documents(
            run,
            rtype,
            update_mode=update_mode,
            typed=typed_fields,
            draft=conv.leave if rtype == RequestType.LEAVE else conv.claim,
            user_name=state["deps"].user_name,
        )
        typed_fields = effects.fields
        notices.extend(effects.notices)
        doc_intro = effects.intro
        # "could not be read on the document" is asked by the backend itself, in its own words
        turn = turn.model_copy(
            update={
                "ambiguities": [a for a in turn.ambiguities if not docs.is_document_ambiguity(a)]
            }
        )

    skip = _ambiguous_fields(turn.ambiguities, rtype)
    if rtype == RequestType.LEAVE:
        assert isinstance(typed_fields, LeaveFields)
        set_fields = _apply_leave(conv, typed_fields, skip, notices)
    else:
        assert isinstance(typed_fields, ClaimFields)
        set_fields = _apply_claim(conv, typed_fields, skip, notices)

    if rtype == RequestType.LEAVE:
        conv.leave = normalise_leave_slots(conv.leave)  # e.g. mirror a one-day half-day part
        if _awaiting_end_date(conv) and _is_one_day_reply(state["message"]):
            conv.leave.end_date = conv.leave.start_date  # "just one day" (an LLM end date wins)
            set_fields.append("end_date")
    _track_document_fields(state, conv, rtype, before, set_fields, effects, notices)
    after = _snapshot(conv)
    changed = after != before
    if changed:
        superseded = _supersede_open_card(conv, superseded)
    detail = (
        f"{rtype.value}: set {', '.join(set_fields)}"
        if set_fields
        else f"{rtype.value}: no new fields"
    )
    if turn.ambiguities:
        detail += "; held back ambiguous values"
    update: dict[str, Any] = {
        "conv": conv,
        "notices": notices,
        "superseded": superseded,
        "doc_intro": doc_intro,
        "trace": _trace(state, "merge", "Draft updated", detail, started=started),
    }

    if turn.ambiguities:
        points = " ".join(f"({i}) {scrub(a)}" for i, a in enumerate(turn.ambiguities, start=1))
        update["reply"] = Reply(
            _join(
                notices, f"Before I go on I need to check {points} Could you clarify that for me?"
            )
        )
        return update
    if not changed and conv.open_card() is not None:
        update["reply"] = Reply(
            _join(
                notices,
                "That is already what the card above shows. Press the button on the card to "
                "continue, or tell me what to change.",
            )
        )
    return update


def route_after_merge(state: TurnState) -> str:
    return "respond" if state.get("reply") is not None else "validate"


# -- update / cancel targets -------------------------------------------------------------------
def prepare_update(state: TurnState) -> dict[str, Any]:
    started = time.perf_counter()
    deps, turn, conv = state["deps"], state["turn"], state["conv"]
    ref: RequestRef | None = turn.target
    forced = state.get("forced_target")
    card = conv.open_card()
    if turn.intent == Intent.PROVIDE_DETAILS and card is not None and card.request_id is not None:
        forced = (card.request_type, card.request_id)
    if forced is not None:
        ref = RequestRef(request_type=forced[0], request_id=forced[1])
    elif conv.editing_request_id is not None and (
        ref is None or (ref.request_id is None and not ref.hint)
    ):
        ref = RequestRef(request_type=conv.active_request_type, request_id=conv.editing_request_id)
    resolved = resolve_target(deps.session, deps.user_id, ref, "change")
    if isinstance(resolved, Unresolved):
        return {
            "reply": Reply(_with_notices(state, resolved.message)),
            "trace": _trace(
                state,
                "validate",
                "Could not resolve the request",
                "no unique editable request of yours matched",
                ok=False,
                started=started,
            ),
        }
    req = resolved.request
    notices = list(state.get("notices", []))
    superseded = list(state.get("superseded", []))
    if conv.editing_request_id != req.id or conv.active_request_type != req.request_type:
        if conv.has_draft():
            notices.append(f"I set aside {_draft_label(conv)}.")
        superseded = _supersede_open_card(conv, superseded)
        conv.reset_draft()
        conv.active_request_type = req.request_type
        conv.editing_request_id = req.id
        slots = slots_from_request(req)
        if isinstance(slots, LeaveSlots):
            conv.leave = slots
        else:
            conv.claim = slots
        conv.original = request_values(req)
    return {
        "conv": conv,
        "mode": "update",
        "notices": notices,
        "superseded": superseded,
        "trace": _trace(
            state,
            "validate",
            "Found your request",
            f"{req.request_type.value} #{req.id} ({status_label(req.status)})",
            started=started,
        ),
    }


def route_after_prepare_update(state: TurnState) -> str:
    return "respond" if state.get("reply") is not None else "merge"


def prepare_cancel(state: TurnState) -> dict[str, Any]:
    started = time.perf_counter()
    deps, turn, conv = state["deps"], state["turn"], state["conv"]
    ref = turn.target
    if conv.editing_request_id is not None and (
        ref is None or (ref.request_id is None and not ref.hint)
    ):
        ref = RequestRef(request_type=conv.active_request_type, request_id=conv.editing_request_id)
    resolved = resolve_target(deps.session, deps.user_id, ref, "cancel")
    if isinstance(resolved, Unresolved):
        return {
            "reply": Reply(_with_notices(state, resolved.message)),
            "trace": _trace(
                state,
                "validate",
                "Could not resolve the request",
                "no unique cancellable request of yours matched",
                ok=False,
                started=started,
            ),
        }
    req = resolved.request
    superseded = _supersede_open_card(conv, list(state.get("superseded", [])))
    values = request_values(req)
    new = card_builders.display_values(
        req.request_type,
        values,
        working_days=values.get("working_days"),
        email=deps.user_email,
        status_label=status_label(req.status),
    )
    card = card_builders.build_card(
        action="cancel", request_type=req.request_type, request_id=req.id, new=new
    )
    conv.pending_card = PendingCard(
        card_id=card.card_id,
        action="cancel",
        request_type=req.request_type,
        request_id=req.id,
        payload_hash=payload_hash("cancel", req.id, {}),
    )
    text = _with_notices(
        state,
        f"You are about to cancel {noun(req.request_type)} #{req.id}. Nothing is cancelled "
        "until you press the button.",
    )
    return {
        "conv": conv,
        "superseded": superseded,
        "reply": Reply(text, ui=card),
        "trace": _trace(
            state,
            "decide",
            "Cancellation card ready",
            f"{req.request_type.value} #{req.id} ({status_label(req.status)})",
            started=started,
        ),
    }


# -- validate / decide -------------------------------------------------------------------------
def validate(state: TurnState) -> dict[str, Any]:
    started = time.perf_counter()
    deps, conv = state["deps"], state["conv"]
    rtype = conv.active_request_type
    assert rtype is not None
    kwargs = {
        "employee_id": deps.user_id,
        "employee_email": deps.user_email,
        "today": deps.today,
        "editing_request_id": conv.editing_request_id,
    }
    if rtype == RequestType.LEAVE:
        outcome = validate_leave(deps.session, conv.leave, **kwargs)
    else:
        outcome = validate_claim(deps.session, conv.claim, **kwargs)
    if isinstance(outcome, Missing):
        detail, ok = f"missing: {outcome.field}", True
    elif isinstance(outcome, Problem):
        detail, ok = f"{outcome.field}: rejected", False
    else:
        detail, ok = "all checks passed", True
    return {
        "outcome": outcome,
        "trace": _trace(
            state, "validate", "Checked by the backend", detail, ok=ok, started=started
        ),
    }


def decide(state: TurnState) -> dict[str, Any]:
    started = time.perf_counter()
    deps, conv, turn = state["deps"], state["conv"], state["turn"]
    outcome = state["outcome"]
    rtype = conv.active_request_type
    assert rtype is not None

    if isinstance(outcome, Problem):
        conv.awaiting = outcome.field
        message = outcome.message
        if outcome.field == "currency" and "currency" in conv.sources:
            currency = (conv.claim.currency or "").strip().upper()
            message = (
                f"The receipt shows {scrub(currency, 12)}, but claims are accepted in HKD only "
                "(I do not convert). What is the amount in HKD?"
            )
        return {
            "conv": conv,
            "reply": Reply(_with_notices(state, message)),
            "trace": _trace(
                state,
                "decide",
                "Asked to fix a value",
                f"ask_followup: {outcome.field}",
                started=started,
            ),
        }
    if isinstance(outcome, Missing):
        conv.awaiting = outcome.field
        unread_file = conv.doc_unread.get(outcome.field)
        document_question = (
            docs.unread_question(
                outcome.field,
                unread_file,
                start_date=conv.leave.start_date,
                days_advised=conv.doc_days_advised,
            )
            if unread_file
            else None
        )
        if document_question is not None:
            question = document_question
        elif outcome.field == "end_date" and conv.leave.start_date is not None:
            question = (
                f"Is {fmt_date(conv.leave.start_date)} just one day, or do you want leave until "
                "another date? (Reply 'just one day' or give the end date.)"
            )
        else:
            question = (
                _wording_ok(turn.followup_question, outcome.field)
                or _FIELD_QUESTIONS[outcome.field]
            )
        return {
            "conv": conv,
            "reply": Reply(_with_notices(state, question)),
            "trace": _trace(
                state,
                "decide",
                "Asked for a missing field",
                f"ask_followup: {outcome.field}",
                started=started,
            ),
        }

    conv.awaiting = None
    values = normalised_values(conv, rtype)
    working_days = fmt_days(outcome.days.working_days) if isinstance(outcome, ValidLeave) else None
    new = card_builders.display_values(
        rtype, values, working_days=working_days, email=deps.user_email
    )
    warnings = [*outcome.warnings, *docs.document_warnings(conv, values)]
    doc_fields = docs.document_card_fields(conv)
    attached = docs.attachment_infos(deps.session, conv.attachment_ids, deps.user_id)

    if conv.editing_request_id is not None:
        original = conv.original or {}
        req = get_own_request(deps.session, deps.user_id, rtype, conv.editing_request_id)
        if req is None:
            conv.reset_draft()
            return {
                "conv": conv,
                "reply": Reply("I can't find that request any more, so I stopped the change."),
                "trace": _trace(
                    state,
                    "decide",
                    "Request vanished",
                    "editing stopped",
                    ok=False,
                    started=started,
                ),
            }
        if req.status not in EDITABLE_STATUSES:
            conv.reset_draft()
            return {
                "conv": conv,
                "reply": Reply(not_editable_message(req, "change")),
                "trace": _trace(
                    state,
                    "decide",
                    "Request is final",
                    status_label(req.status),
                    ok=False,
                    started=started,
                ),
            }
        changed = [k for k in values if original.get(k) != values[k]]
        if not changed:
            if req.status in RETRYABLE_STATUSES:
                return _retry_offer(state, req, started)
            conv.awaiting = "changes"
            return {
                "conv": conv,
                "reply": Reply(
                    _with_notices(
                        state,
                        f"{noun(rtype).capitalize()} #{req.id} is currently {describe(req)}. "
                        "What would you like to change?",
                    )
                ),
                "trace": _trace(
                    state,
                    "decide",
                    "Nothing to change yet",
                    "asked what to change",
                    started=started,
                ),
            }
        old = card_builders.display_values(
            rtype,
            {k: original.get(k) for k in values},
            working_days=original.get("working_days"),
            email=deps.user_email,
        )
        card = card_builders.build_card(
            action="update",
            request_type=rtype,
            request_id=req.id,
            new=new,
            old=old,
            warnings=warnings,
            document_fields=doc_fields,
            attachments=attached,
        )
        conv.pending_card = PendingCard(
            card_id=card.card_id,
            action="update",
            request_type=rtype,
            request_id=req.id,
            payload_hash=payload_hash("update", req.id, values),
        )
        text = _with_notices(
            state,
            _intro(state)
            + f'Here is what would change on {noun(rtype)} #{req.id}. Press "Save changes" to '
            "apply it (it is sent to the mock API again), or tell me what else to adjust.",
        )
    else:
        card = card_builders.build_card(
            action="create",
            request_type=rtype,
            request_id=None,
            new=new,
            warnings=warnings,
            document_fields=doc_fields,
            attachments=attached,
        )
        conv.pending_card = PendingCard(
            card_id=card.card_id,
            action="create",
            request_type=rtype,
            payload_hash=payload_hash("create", None, values),
        )
        what = "leave application" if rtype == RequestType.LEAVE else "claim"
        text = _with_notices(
            state,
            _intro(state)
            + f"Please check your {what} below. Nothing is saved or submitted until you press "
            "Submit.",
        )
    return {
        "conv": conv,
        "reply": Reply(text, ui=card),
        "trace": _trace(
            state,
            "decide",
            "Confirmation card ready",
            f"{card.action} {rtype.value}" + (f" ({len(warnings)} warning)" if warnings else ""),
            started=started,
        ),
    }


def _intro(state: TurnState) -> str:
    """ "I read <file> and filled in ..." in front of a card built from a document."""
    intro = state.get("doc_intro")
    return f"{intro} " if intro else ""


def _retry_offer(state: TurnState, req: Req, started: float) -> dict[str, Any]:
    deps, conv = state["deps"], state["conv"]
    values = request_values(req)
    new = card_builders.display_values(
        req.request_type,
        values,
        working_days=values.get("working_days"),
        email=deps.user_email,
        status_label=status_label(req.status),
    )
    card = card_builders.build_card(
        action="retry", request_type=req.request_type, request_id=req.id, new=new
    )
    conv.pending_card = PendingCard(
        card_id=card.card_id,
        action="retry",
        request_type=req.request_type,
        request_id=req.id,
        payload_hash=payload_hash("retry", req.id, {}),
    )
    conv.reset_draft()
    return {
        "conv": conv,
        "reply": Reply(
            _with_notices(
                state,
                f"{noun(req.request_type).capitalize()} #{req.id} was saved but not submitted. "
                "Press Retry to send it again, or tell me what to change first.",
            ),
            ui=card,
        ),
        "trace": _trace(
            state,
            "decide",
            "Retry card ready",
            f"{req.request_type.value} #{req.id}",
            started=started,
        ),
    }


def respond(state: TurnState) -> dict[str, Any]:
    started = time.perf_counter()
    reply = state.get("reply")
    if reply is None:  # defensive: every path sets a reply
        reply = Reply(UNCLEAR_TEXT)
    trace = _trace(
        state,
        "respond",
        "Reply prepared",
        "card" if reply.ui is not None else "text",
        started=started,
    )
    conv = state["conv"]
    result = TurnResult(
        reply=reply,
        state=conv,
        trace=trace,
        superseded=list(state.get("superseded", [])),
        state_changed=dump_state(conv) != state["before"],
        extractions=dict(state.get("extractions", {})),
    )
    return {"result": result, "trace": trace}


def _build() -> Any:
    g = StateGraph(TurnState)
    for name, fn in {
        "load_context": load_context,
        "remind": remind,
        "understand": understand,
        "documents": documents,
        "error_reply": error_reply,
        "refuse": refuse_other_user,
        "clarify": clarify_low_confidence,
        "hold_cancel": hold_cancel,
        "explain": explain,
        "status": status,
        "merge": merge,
        "prepare_update": prepare_update,
        "prepare_cancel": prepare_cancel,
        "validate": validate,
        "decide": decide,
        "respond": respond,
    }.items():
        g.add_node(name, fn)
    g.add_edge(START, "load_context")
    g.add_conditional_edges(
        "load_context",
        route_precheck,
        {"understand": "understand", "remind_yes": "remind", "remind_no": "remind"},
    )
    g.add_conditional_edges(
        "understand",
        route_after_understand,
        {"error": "error_reply", "documents": "documents"},
    )
    g.add_conditional_edges(
        "documents",
        route_after_documents,
        {
            "respond": "respond",
            "error": "error_reply",
            "refuse": "refuse",
            "clarify": "clarify",
            "hold_cancel": "hold_cancel",
            "merge": "merge",
            "prepare_update": "prepare_update",
            "prepare_cancel": "prepare_cancel",
            "status": "status",
            "explain": "explain",
        },
    )
    g.add_conditional_edges(
        "merge", route_after_merge, {"respond": "respond", "validate": "validate"}
    )
    g.add_conditional_edges(
        "prepare_update", route_after_prepare_update, {"respond": "respond", "merge": "merge"}
    )
    g.add_edge("validate", "decide")
    for node in (
        "remind",
        "error_reply",
        "refuse",
        "clarify",
        "hold_cancel",
        "explain",
        "status",
        "prepare_cancel",
        "decide",
    ):
        g.add_edge(node, "respond")
    g.add_edge("respond", END)
    return g.compile()


_GRAPH = _build()


def run_turn(
    deps: TurnDeps,
    conv: ConversationState,
    message: str,
    history: list[ChatTurn],
) -> TurnResult:
    """Run one user message through the graph. Never mutates ``conv`` (works on a copy)."""
    working = conv.model_copy(deep=True)
    initial: TurnState = {
        "deps": deps,
        "message": message,
        "conv": working,
        "before": dump_state(conv),
        "history": history,
        "trace": [],
        "notices": [],
        "superseded": [],
        "reply": None,
        "error": None,
        "mode": None,
    }
    final = _GRAPH.invoke(initial)
    return final["result"]


__all__ = ["Reply", "TurnDeps", "TurnResult", "run_turn"]
