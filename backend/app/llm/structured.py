"""Shared structured-output plumbing for the LLM providers (Gemini, Ollama, ...).

The thin wire schema (dates as ISO strings, no constraints) is what a model is asked to
produce; ``parse_turn`` normalises it defensively and validates it with ``AgentTurn``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.domain.enums import ClaimType, DayPart, LeaveType, RequestStatus, RequestType
from app.llm.currency import mentions_dollars, normalise_currency, says_hkd, says_usd
from app.llm.schemas import AgentTurn, DocType, DocumentExtraction, Intent

ATTACHMENT_MIME_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif", "application/pdf"}
)


# --- Thin wire schema: what Gemini is asked to produce (dates as ISO strings, no constraints) ---
class _WireLeave(BaseModel):
    model_config = ConfigDict(extra="ignore")

    leave_type: LeaveType | None = None
    start_date: str | None = None
    end_date: str | None = None
    start_day_part: DayPart | None = None
    end_day_part: DayPart | None = None


class _WireClaim(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claim_type: ClaimType | None = None
    amount: float | None = None
    currency: str | None = None
    receipt_date: str | None = None


class _WireRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    request_id: int | None = None
    request_type: RequestType | None = None
    hint: str | None = None


class _WireStatusQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")

    request_type: RequestType | None = None
    request_id: int | None = None
    status: RequestStatus | None = None


class _WireDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int = 0
    doc_type: DocType
    readable: bool = True
    summary: str | None = None
    person_name: str | None = None
    provider_name: str | None = None
    issue_date: str | None = None
    rest_start_date: str | None = None
    rest_end_date: str | None = None
    days_advised: float | None = None
    receipt_date: str | None = None
    total_amount: float | None = None
    currency: str | None = None
    suggested_claim_type: ClaimType | None = None
    unreadable_fields: list[str] = []
    confidence: float | None = None


class WireTurn(BaseModel):
    """JSON shape requested from Gemini; converted into ``AgentTurn`` by validation."""

    model_config = ConfigDict(extra="ignore")

    intent: Intent
    request_type: RequestType | None = None
    leave: _WireLeave | None = None
    claim: _WireClaim | None = None
    target: _WireRef | None = None
    status_query: _WireStatusQuery | None = None
    documents: list[_WireDocument] = []
    ambiguities: list[str] = []
    followup_question: str | None = None
    confidence: float | None = None
    rationale: str | None = None


def _inline_refs(node: Any, defs: Mapping[str, Any]) -> Any:
    """Inline ``$ref`` and drop keywords Gemini does not need (title, default, $defs)."""
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline_refs(defs[node["$ref"].rsplit("/", 1)[-1]], defs)
        return {
            key: _inline_refs(value, defs)
            for key, value in node.items()
            if key not in {"title", "default", "$defs"}
        }
    if isinstance(node, list):
        return [_inline_refs(item, defs) for item in node]
    return node


def build_response_schema() -> dict[str, Any]:
    raw = WireTurn.model_json_schema()
    return _inline_refs(raw, raw.get("$defs", {}))


RESPONSE_SCHEMA: dict[str, Any] = build_response_schema()


def strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _limit(value: Any, size: int) -> Any:
    return value[:size] if isinstance(value, str) else value


def _normalise_document(position: int, doc: Any) -> Any:
    if not isinstance(doc, dict):
        return doc
    out = dict(doc)
    out["index"] = position  # alignment is by position, whatever the model wrote
    for key, size in (("summary", 200), ("person_name", 120), ("provider_name", 120)):
        out[key] = _limit(out.get(key), size)
    fields = out.get("unreadable_fields")
    out["unreadable_fields"] = [str(f)[:60] for f in fields[:8]] if isinstance(fields, list) else []
    conf = out.get("confidence")
    if isinstance(conf, int | float) and not isinstance(conf, bool):
        out["confidence"] = min(1.0, max(0.0, float(conf)))
    return out


def normalise_output(data: dict[str, Any], max_documents: int = 3) -> dict[str, Any]:
    """Defensive length/range clamps so harmless overruns do not cost a retry."""
    out = dict(data)
    documents = out.get("documents")
    if isinstance(documents, list):
        out["documents"] = [
            _normalise_document(i, d) for i, d in enumerate(documents[:max_documents])
        ]
    elif documents is None:
        out["documents"] = []
    out["followup_question"] = _limit(out.get("followup_question"), 240)
    out["rationale"] = _limit(out.get("rationale"), 200)
    ambiguities = out.get("ambiguities")
    if isinstance(ambiguities, list):
        out["ambiguities"] = [str(a)[:200] for a in ambiguities[:5]]
    elif ambiguities is None:
        out["ambiguities"] = []
    conf = out.get("confidence")
    if isinstance(conf, int | float) and not isinstance(conf, bool):
        out["confidence"] = min(1.0, max(0.0, float(conf)))
    target = out.get("target")
    if isinstance(target, dict):
        out["target"] = {**target, "hint": _limit(target.get("hint"), 120)}
    return out


class InvalidOutput(Exception):
    """The reply was not a valid ``AgentTurn``; ``problem`` names fields only, never values."""

    def __init__(self, problem: str) -> None:
        super().__init__(problem)
        self.problem = problem


def parse_turn(text: str | None, max_documents: int = 3) -> AgentTurn:
    if not text or not text.strip():
        raise InvalidOutput("empty response")
    try:
        data = json.loads(strip_fences(text))
    except ValueError:
        raise InvalidOutput("not valid JSON") from None
    if not isinstance(data, dict):
        raise InvalidOutput("JSON root is not an object")
    try:
        return AgentTurn.model_validate(normalise_output(data, max_documents))
    except ValidationError as exc:
        # Only field paths (never values) go into the corrective hint and the log.
        fields = sorted({".".join(str(p) for p in e["loc"]) or "root" for e in exc.errors()})
        raise InvalidOutput("invalid fields: " + ", ".join(fields[:6])) from None


def align_documents(turn: AgentTurn, count: int) -> AgentTurn:
    """Exactly one document entry per attachment: drop extras, pad missing as unreadable."""
    docs = list(turn.documents[:count])
    for i in range(len(docs), count):
        docs.append(DocumentExtraction(index=i, doc_type=DocType.UNREADABLE, readable=False))
    return turn.model_copy(update={"documents": docs})


# --- Flat wire schema for small local models (Ollama) ------------------------------------------
# Constrained decoding with ``anyOf: [enum, null]`` and nested optional objects makes small
# models drop explicit fields. Here every key is always present: "" means unknown,
# ``target_request_id`` 0 means none, and the amount is a string. ``flat_to_turn_dict`` maps the
# result to the normal ``AgentTurn`` shape, which ``parse_flat_turn`` then validates.
_INTENTS = [i.value for i in Intent]
_TEXT = {"type": "string"}
_DOC_TYPES = [d.value for d in DocType]


def _opt_enum(values: Any) -> dict[str, Any]:
    return {"type": "string", "enum": ["", *[getattr(v, "value", v) for v in values]]}


_FLAT_TURN_PROPS: dict[str, Any] = {
    "intent": {"type": "string", "enum": _INTENTS},
    "request_type": _opt_enum(RequestType),
    "leave_type": _opt_enum(LeaveType),
    "start_date": _TEXT,
    "end_date": _TEXT,
    "start_day_part": _opt_enum(DayPart),
    "end_day_part": _opt_enum(DayPart),
    "claim_type": _opt_enum(ClaimType),
    "amount": _TEXT,
    "currency": _TEXT,
    "receipt_date": _TEXT,
    "target_request_id": {"type": "integer"},
    "confidence": {"type": "number"},
}
_FLAT_DOC_PROPS: dict[str, Any] = {
    "doc_type": {"type": "string", "enum": _DOC_TYPES},
    "person_name": _TEXT,
    "provider_name": _TEXT,
    "issue_date": _TEXT,
    "rest_start_date": _TEXT,
    "rest_end_date": _TEXT,
    "days_advised": _TEXT,
    "receipt_date": _TEXT,
    "total_amount": _TEXT,
    "currency": _TEXT,
    "suggested_claim_type": _opt_enum(ClaimType),
    "unreadable_fields": {"type": "array", "items": _TEXT},
}


def build_flat_schema(document_count: int = 0) -> dict[str, Any]:
    """JSON schema for the flat reply; ``documents`` exists only when readable documents follow."""
    props: dict[str, Any] = dict(_FLAT_TURN_PROPS)
    if document_count:
        props["documents"] = {
            "type": "array",
            "minItems": document_count,
            "maxItems": document_count,
            "items": {
                "type": "object",
                "properties": _FLAT_DOC_PROPS,
                "required": list(_FLAT_DOC_PROPS),
            },
        }
    return {"type": "object", "properties": props, "required": list(props)}


def _s(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _none(value: Any) -> str | None:
    return _s(value) or None


def _currency(value: Any) -> str | None:
    return normalise_currency(_s(value))


def _parse_number(value: Any, field: str) -> float | None:
    text = _s(value).replace(",", "")
    if not text:
        return None
    cleaned = "".join(ch for ch in text if ch.isdigit() or ch in ".-")
    try:
        return float(cleaned)
    except ValueError:
        raise InvalidOutput(f"invalid fields: {field}") from None


def _positive_id(value: Any) -> int | None:
    """Accepts 12, 12.0, "12" and "#12" (some models return the id as a string)."""
    text = _s(value).lstrip("#").strip()
    try:
        number = int(float(text)) if text else 0
    except ValueError:
        return None
    return number if number > 0 else None


def _compact(fields: dict[str, Any]) -> dict[str, Any] | None:
    return fields if any(v is not None for v in fields.values()) else None


_REQUIRED_FIELDS = {
    "sick_note": ("rest_start_date", "rest_end_date"),
    "receipt": ("receipt_date", "total_amount"),
}


def _unreadable_fields(doc_type: str, doc: dict[str, Any]) -> list[str]:
    """The required fields of this document type that the model left empty. Computed here
    instead of trusting the model's own list (a small model lists unrelated or already-read
    fields, or none at all)."""
    return [name for name in _REQUIRED_FIELDS.get(doc_type, ()) if not _s(doc.get(name))]


_MONTH_NAMES = [
    (full[:3], full)
    for full in (
        "january february march april may june july august september october november december"
    ).split()
]
_DATE_FORMATS = ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%d/%m/%Y")


def _doc_date(value: Any) -> str | None:
    """A date read from a document as ISO text, or None (unreadable) if it is not a date."""
    text = _s(value)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _date_in_text(iso: str | None, text: str) -> str | None:
    """Keep a document date only if its year, month and day really occur in the OCR text
    (small models invent today's date when the printed one is missing)."""
    if iso is None or not text:
        return iso
    year, month, day = (int(part) for part in iso.split("-"))
    lowered = text.lower()
    month_names = _MONTH_NAMES[month - 1]
    has_month = any(name in lowered for name in month_names) or re.search(
        rf"(?<!\d)0?{month}(?!\d)", lowered
    )
    has_day = re.search(rf"(?<!\d)0?{day}(?!\d)", lowered)
    return iso if str(year) in lowered and has_month and has_day else None


def _amount_in_text(value: float | None, text: str) -> float | None:
    if value is None or not text:
        return value
    for token in re.findall(r"\d[\d,]*\.?\d*", text):
        try:
            if abs(float(token.replace(",", "")) - value) < 0.005:
                return value
        except ValueError:
            continue
    return None


def _flat_document(position: int, raw: Any, source_text: str = "") -> dict[str, Any]:
    doc = raw if isinstance(raw, dict) else {}
    doc_type = _s(doc.get("doc_type")) or DocType.UNREADABLE.value
    if doc_type == DocType.OTHER.value and _s(doc.get("total_amount")):
        doc_type = DocType.RECEIPT.value  # a "total" with no rest period is a receipt/invoice
    cleaned = {
        "index": position,
        "doc_type": doc_type,
        "readable": doc_type != DocType.UNREADABLE.value,
        "person_name": _none(doc.get("person_name")),
        "provider_name": _none(doc.get("provider_name")),
        "issue_date": _date_in_text(_doc_date(doc.get("issue_date")), source_text),
        "rest_start_date": _date_in_text(_doc_date(doc.get("rest_start_date")), source_text),
        "rest_end_date": _date_in_text(_doc_date(doc.get("rest_end_date")), source_text),
        "days_advised": _parse_number(doc.get("days_advised"), "documents.days_advised"),
        "receipt_date": _date_in_text(_doc_date(doc.get("receipt_date")), source_text),
        "total_amount": _amount_in_text(
            _parse_number(doc.get("total_amount"), "documents.total_amount"), source_text
        ),
        "currency": _currency(doc.get("currency")),
        "suggested_claim_type": _none(doc.get("suggested_claim_type")),
    }
    cleaned["unreadable_fields"] = _unreadable_fields(doc_type, cleaned)
    return cleaned


def _fill_from_documents(out: dict[str, Any], override: bool) -> None:
    """Small models often leave the top-level fields empty although the document was read.
    Empty fields are filled from the model's own document extraction. When the user's message
    carries no values of its own (``override``) the document is the only source, so its
    dates/amount replace whatever the model put at the top level (models fill today's date
    when a printed date is missing)."""
    docs = [d for d in out["documents"] if d["doc_type"] != DocType.UNREADABLE.value]
    if not docs or out["intent"] not in {"create_leave", "create_claim", "unclear"}:
        return
    doc = docs[0]
    if doc["doc_type"] == DocType.SICK_NOTE.value and out["claim"] is None:
        leave = dict(out["leave"] or {})
        for key, value in (
            ("leave_type", "sick"),
            ("start_date", doc["rest_start_date"]),
            ("end_date", doc["rest_end_date"]),
        ):
            leave[key] = value if override and key != "leave_type" else leave.get(key) or value
        out["leave"] = leave
        out["request_type"] = out["request_type"] or "leave"
        if out["intent"] == "unclear":
            out["intent"] = "create_leave"
    elif doc["doc_type"] == DocType.RECEIPT.value and out["leave"] is None:
        claim = dict(out["claim"] or {})
        for key, value in (
            ("claim_type", doc["suggested_claim_type"]),
            ("amount", doc["total_amount"]),
            ("currency", doc["currency"]),
            ("receipt_date", doc["receipt_date"]),
        ):
            keep = claim.get(key) is not None and not (override and key != "claim_type")
            claim[key] = claim[key] if keep else value
        out["claim"] = claim
        out["request_type"] = out["request_type"] or "claim"
        if out["intent"] == "unclear":
            out["intent"] = "create_claim"


def flat_to_turn_dict(
    data: dict[str, Any],
    positions: Sequence[int] = (),
    vague_phrase: str = "",
    text_has_values: bool = True,
    source_texts: Sequence[str] = (),
) -> dict[str, Any]:
    """Map the flat reply to the ``AgentTurn`` JSON shape ("" -> None, 0 -> None, str -> float).

    ``positions`` are the attachment indexes of the documents the model saw, in order.
    ``vague_phrase`` is a vague date phrase the BACKEND found in the message ("next week"); it
    becomes an ambiguity when the relevant date is empty (the model's own notes are not used).
    """
    leave = _compact(
        {
            "leave_type": _none(data.get("leave_type")),
            "start_date": _none(data.get("start_date")),
            "end_date": _none(data.get("end_date")),
            "start_day_part": _none(data.get("start_day_part")),
            "end_day_part": _none(data.get("end_day_part")),
        }
    )
    claim = _compact(
        {
            "claim_type": _none(data.get("claim_type")),
            "amount": _parse_number(data.get("amount"), "amount"),
            "currency": _currency(data.get("currency")),
            "receipt_date": _none(data.get("receipt_date")),
        }
    )
    intent = _s(data.get("intent"))
    form = _none(data.get("request_type")) or {
        "create_leave": "leave",
        "create_claim": "claim",
    }.get(intent)
    if form == "claim" and not positions:
        leave = None  # some models copy dates into the leave fields of a claim turn
    elif form == "leave" and not positions:
        claim = None
    if leave and leave["start_day_part"] != leave["end_day_part"]:
        same_day = leave["start_date"] == leave["end_date"]
        if same_day or not (leave["start_date"] and leave["end_date"]):
            # A 7B model sometimes emits am/pm for a plain day. Only equal parts are valid on
            # one day, so drop the unreliable pair rather than invent a half day.
            leave["start_day_part"] = leave["end_day_part"] = None
    request_type = _none(data.get("request_type"))
    if request_type is None and (leave is None) != (claim is None):
        request_type = "leave" if leave else "claim"
    target_id = _positive_id(data.get("target_request_id"))
    raw_docs = data.get("documents")
    texts = dict(zip(positions, source_texts, strict=False))
    confidence = data.get("confidence")
    vague = _s(vague_phrase)
    out: dict[str, Any] = {
        "intent": intent,
        "request_type": request_type,
        "leave": leave,
        "claim": claim,
        "target": (
            {"request_id": target_id, "request_type": request_type}
            if target_id and intent in {"update_request", "cancel_request"}
            else None
        ),
        "status_query": (
            {"request_type": request_type, "request_id": target_id}
            if intent == "check_status" and (request_type or target_id)
            else None
        ),
        "documents": [
            _flat_document(position, doc, texts.get(position, ""))
            for position, doc in zip(positions, raw_docs, strict=False)
        ]
        if isinstance(raw_docs, list)
        else [],
        # A vague-date note only matters when the relevant date is empty.
        "ambiguities": (
            [f"Date is not specific: {vague[:80]}"]
            if vague
            and intent in {"create_leave", "create_claim", "provide_details", "update_request"}
            and not (leave and leave["start_date"])
            and not (claim and claim["receipt_date"])
            else []
        ),
        "confidence": (
            confidence
            if isinstance(confidence, int | float) and not isinstance(confidence, bool)
            else None
        ),
    }
    if positions:
        _fill_from_documents(out, override=not text_has_values)
    return out


def with_unreadable_documents(turn: AgentTurn, total: int) -> AgentTurn:
    """One document entry per attachment index (0..total-1); missing ones are unreadable."""
    by_index = {d.index: d for d in turn.documents if 0 <= d.index < total}
    docs = [
        by_index.get(i) or DocumentExtraction(index=i, doc_type=DocType.UNREADABLE, readable=False)
        for i in range(total)
    ]
    return turn.model_copy(update={"documents": docs})


def parse_flat_turn(
    text: str | None,
    positions: Sequence[int] = (),
    total_documents: int = 0,
    vague_phrase: str = "",
    text_has_values: bool = True,
    source_texts: Sequence[str] = (),
) -> AgentTurn:
    """Parse the flat reply into a validated ``AgentTurn``.

    ``positions`` are the attachment indexes of the documents the model was shown (readable
    ones) and ``source_texts`` their OCR text (dates/amounts not present in it are dropped);
    every other attachment (up to ``total_documents``) is recorded as unreadable.
    """
    if not text or not text.strip():
        raise InvalidOutput("empty response")
    try:
        data = json.loads(strip_fences(text))
    except ValueError:
        raise InvalidOutput("not valid JSON") from None
    if not isinstance(data, dict):
        raise InvalidOutput("JSON root is not an object")
    mapped = flat_to_turn_dict(data, positions, vague_phrase, text_has_values, source_texts)
    try:
        turn = AgentTurn.model_validate(normalise_output(mapped, len(positions)))
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) or "root" for e in exc.errors()})
        raise InvalidOutput("invalid fields: " + ", ".join(fields[:6])) from None
    # normalise_output numbered the documents 0..n-1; restore the real attachment positions.
    docs = [
        d.model_copy(update={"index": pos})
        for d, pos in zip(turn.documents, positions, strict=False)
    ]
    return with_unreadable_documents(turn.model_copy(update={"documents": docs}), total_documents)


def correct_currency(turn: AgentTurn, message: str) -> AgentTurn:
    """The company is in Hong Kong: a bare ``$``, ``HK$`` or "dollars" means HKD. Small models
    answer USD for ``$`` (and sometimes HKD for "US dollars"); the message decides. Text turns
    only. ``USD`` / ``US$`` / "US dollars" stay USD and are rejected later by the backend."""
    claim = turn.claim
    if claim is None or turn.documents:
        return turn
    current = normalise_currency(claim.currency)
    fixed = current
    if says_usd(message) and not says_hkd(message):
        fixed = "USD"
    elif current == "USD":  # the model's guess, not the user's words
        fixed = "HKD" if mentions_dollars(message) else None
    if fixed == claim.currency:
        return turn
    return turn.model_copy(update={"claim": claim.model_copy(update={"currency": fixed})})


_LEAVE_TYPE_WORDS = re.compile(
    r"annual|vacation|holiday|sick|unwell|\bill\b|illness|doctor|medical|flu\b|fever|personal"
    r"|family|casual|unpaid|no pay|without pay|compassionate|maternity|paternity|marriage",
    re.IGNORECASE,
)


def drop_invented_leave_type(turn: AgentTurn, message: str) -> AgentTurn:
    """ "Take Monday off" names no leave type, yet some models pick ``annual``. A type the
    user never hinted at is dropped so the backend asks for it. Text-only new requests."""
    leave = turn.leave
    if (
        leave is None
        or leave.leave_type is None
        or turn.documents
        or turn.intent != Intent.CREATE_LEAVE
        or _LEAVE_TYPE_WORDS.search(message)
    ):
        return turn
    return turn.model_copy(update={"leave": leave.model_copy(update={"leave_type": None})})
