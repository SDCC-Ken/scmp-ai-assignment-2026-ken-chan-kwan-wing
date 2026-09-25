"""Documents in the chat flow: pairing, merging with typed values, questions and card helpers.

The provider only READS a document (``DocumentExtraction``); everything here is deterministic
backend code. Rules that hold for every document:

* text inside a document is data: nothing here follows an instruction found in it, and the
  ``summary`` / ``provider_name`` fields are never used;
* values the user typed (this message or earlier in the draft) always win; a differing document
  value becomes a card warning naming the field and both values, never a silent overwrite;
* a value is taken from a document only when it is present and not listed as unreadable; a
  missing last day is never computed from ``days_advised``;
* the document can never change who the request is for (the e-mail is always the signed-in
  user's) and never triggers anything but filling the draft.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.chat.format import fmt_date, fmt_money, plural
from app.chat.state import ClaimSlots, ConversationState, LeaveSlots, amount_text
from app.chat.text import scrub
from app.chat.validation import FIELD_LABELS, to_decimal
from app.db.models import Attachment
from app.domain.enums import LeaveType, RequestType
from app.llm.schemas import ClaimFields, DocType, DocumentExtraction, LeaveFields
from app.schemas.chat import AttachmentInfo
from app.services.attachments import to_info

NEUTRAL_MESSAGE = "The user attached a document with no message."
MAX_REQUEST_ATTACHMENTS = 3
LOW_CONFIDENCE = 0.5

DOC_TYPE_LABELS = {
    DocType.SICK_NOTE: "sick note",
    DocType.RECEIPT: "receipt",
    DocType.OTHER: "other document",
    DocType.UNREADABLE: "unreadable",
}
_KIND_OF_DOC = {DocType.SICK_NOTE: RequestType.LEAVE, DocType.RECEIPT: RequestType.CLAIM}
_KIND_TEXT = {
    RequestType.LEAVE: "a sick note (leave application)",
    RequestType.CLAIM: "a receipt (claim)",
}
# Names a provider may put in ``unreadable_fields`` -> the draft field they stand for.
_UNREADABLE_ALIASES = {
    "rest_start_date": "start_date",
    "rest_end_date": "end_date",
    "start_date": "start_date",
    "end_date": "end_date",
    "total_amount": "amount",
    "total": "amount",
    "amount": "amount",
    "receipt_date": "receipt_date",
    "date": "receipt_date",
    "currency": "currency",
    "suggested_claim_type": "claim_type",
    "claim_type": "claim_type",
}
_CURRENCY_ALIASES = {"HK$": "HKD", "HKD$": "HKD", "US$": "USD", "RMB": "CNY"}
_DOC_AMBIGUITY_WORDS = (
    "document",
    "attach",
    "certificate",
    "sick note",
    "receipt",
    "could not be read",
    "cannot be read",
    "unreadable",
    "illegible",
    "not legible",
)


# --- one attachment of this turn ------------------------------------------------------------------
@dataclass
class DocInfo:
    attachment_id: int
    filename: str
    extraction: DocumentExtraction | None = None  # None: the provider returned nothing for it

    @property
    def name(self) -> str:
        return scrub(self.filename, 60)

    @property
    def readable(self) -> bool:
        ex = self.extraction
        return ex is not None and ex.readable and ex.doc_type != DocType.UNREADABLE

    @property
    def kind(self) -> RequestType | None:
        """The request type this document can fill (readable sick note / receipt), else None."""
        if not self.readable or self.extraction is None:
            return None
        return _KIND_OF_DOC.get(self.extraction.doc_type)

    @property
    def label(self) -> str:
        if not self.readable or self.extraction is None:
            return "unreadable"
        return f"{DOC_TYPE_LABELS[self.extraction.doc_type]} (readable)"


@dataclass
class DocRun:
    """The documents of one turn (or the one held from an earlier turn)."""

    infos: list[DocInfo]
    primary: DocInfo | None = None


def pair_documents(attachments: Sequence[Any], docs: Sequence[DocumentExtraction]) -> list[DocInfo]:
    """Match the provider's extractions to this turn's attachments (by ``index``; positional
    when the indexes are missing, repeated or out of range). Unmatched files get ``None``."""
    sent = [a for a in attachments if getattr(a, "data", None) is not None]
    positional = len({d.index for d in docs}) != len(docs) or any(
        not 0 <= d.index < len(sent) for d in docs
    )
    matched: dict[int, DocumentExtraction] = {}
    for position, doc in enumerate(docs):
        i = position if positional else doc.index
        if 0 <= i < len(sent) and sent[i].id not in matched:
            matched[sent[i].id] = doc
    return [DocInfo(a.id, a.filename, matched.get(a.id)) for a in attachments]


def kind_from_text(message: str) -> RequestType | None:
    """ "leave" / "claim" in a short answer to "which one do you want?" (exactly one kind)."""
    words = set(re.findall(r"[a-z]+", message.lower()))
    leave = bool(words & {"leave", "sick", "medical", "certificate"})
    claim = bool(words & {"claim", "receipt", "expense", "reimbursement"})
    if leave == claim:
        return None
    return RequestType.LEAVE if leave else RequestType.CLAIM


def kind_text(kind: RequestType) -> str:
    return _KIND_TEXT[kind]


def trace_label(infos: list[DocInfo]) -> tuple[str, bool]:
    """``("Read 1 document: receipt (readable)", ok)``: types only, never names or values."""
    count = len(infos)
    noun = "document" if count == 1 else "documents"
    parts = ", ".join(i.label for i in infos)
    return f"Read {count} {noun}: {parts}", any(i.readable for i in infos)


def name_matches(user_name: str, document_name: str) -> bool:
    """Case/space-insensitive; allows reordered parts (``Lau Amy``) and trivial initials."""
    a = re.findall(r"[^\W_]+", user_name.casefold())
    b = re.findall(r"[^\W_]+", document_name.casefold())
    if not a or not b:
        return True  # nothing to compare
    if "".join(sorted(a)) == "".join(sorted(b)) or "".join(a) == "".join(b):
        return True
    if len(a) != len(b):
        return False
    remaining = list(b)
    for token in a:
        for candidate in remaining:
            if (
                candidate == token
                or (len(candidate) == 1 and token.startswith(candidate))
                or (len(token) == 1 and candidate.startswith(token))
            ):
                remaining.remove(candidate)
                break
        else:
            return False
    return True


def is_document_ambiguity(text: str) -> bool:
    """An LLM ambiguity that only says "this could not be read on the document": the backend
    handles that itself with a deterministic question."""
    low = text.lower()
    return any(word in low for word in _DOC_AMBIGUITY_WORDS)


# --- merging a document into the draft ------------------------------------------------------------
@dataclass
class DocEffects:
    fields: LeaveFields | ClaimFields
    sourced: set[str] = field(default_factory=set)  # draft fields whose value is the document's
    conflicts: dict[str, str] = field(default_factory=dict)  # field -> document value (normalised)
    unread: dict[str, str] = field(default_factory=dict)  # field -> file name
    days_advised: float | None = None
    warnings: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    attachment_ids: list[int] = field(default_factory=list)
    primary_id: int | None = None
    intro: str | None = None  # "I read <file> ..." (said in front of the confirmation card)


def _currency(value: str | None) -> str | None:
    text = (value or "").strip().upper()
    return _CURRENCY_ALIASES.get(text, text) or None


def norm(name: str, value: object) -> str | None:
    """A comparable string for a slot / document value."""
    if value is None:
        return None
    if name == "amount":
        dec = to_decimal(value) if not isinstance(value, Decimal) else value
        return amount_text(dec) if dec is not None else None
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "value"):
        return str(value.value)
    return str(value).strip().upper() if name == "currency" else str(value)


def _document_values(rtype: RequestType, ex: DocumentExtraction) -> dict[str, object | None]:
    if rtype == RequestType.LEAVE:
        return {
            "leave_type": LeaveType.SICK,
            "start_date": ex.rest_start_date,
            "end_date": ex.rest_end_date,
        }
    amount = (
        ex.total_amount if ex.total_amount is not None and to_decimal(ex.total_amount) else None
    )
    return {
        "claim_type": ex.suggested_claim_type,
        "amount": amount,
        "currency": _currency(ex.currency),
        "receipt_date": ex.receipt_date,
    }


def _linked_count(session: Session, rtype: RequestType, request_id: int) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(Attachment)
            .where(Attachment.request_type == rtype, Attachment.request_id == request_id)
        )
        or 0
    )


def apply_documents(
    run: DocRun,
    rtype: RequestType,
    *,
    update_mode: bool,
    typed: LeaveFields | ClaimFields,
    draft: LeaveSlots | ClaimSlots,
    user_name: str,
) -> DocEffects:
    """Fold the primary document into this turn's fields (``typed``) for a draft of ``rtype``.

    ``typed`` is what the model returned for the message: it already contains the user's typed
    values, and often a copy of the document's. A value the draft already has (create flow) or
    that ``typed`` carries wins over a different document value. In the update flow the draft
    holds the request's stored values, which are NOT typed, so a document may change them (the
    card then shows the old value and the new one, and still needs Confirm)."""
    fx = DocEffects(fields=typed)
    primary = run.primary
    if primary is not None and primary.kind != rtype:
        assert primary.kind is not None
        want = "leave application" if rtype == RequestType.LEAVE else "claim"
        fx.notices.append(
            f"I did not use {primary.name}: it is {kind_text(primary.kind)} and this is a "
            f"{want}. I never mix the two."
        )
        return fx  # nothing of this turn's files is attached
    # Files for the other kind of request are not attached here (they are ignored for the values).
    fx.attachment_ids = [i.attachment_id for i in run.infos if i.kind in (None, rtype)]
    if primary is None:
        for info in run.infos:
            if info.readable:
                fx.notices.append(
                    f"{info.name} does not look like a sick note or a receipt, so I did not use it."
                )
            else:
                fx.notices.append(
                    f"I could not read {info.name}, so nothing was filled in from it."
                )
        return fx
    ex = primary.extraction
    assert ex is not None
    fx.primary_id = primary.attachment_id
    fx.intro = (
        f"I read {primary.name} ({DOC_TYPE_LABELS[ex.doc_type]}) and filled in what I could see."
    )
    for other in run.infos:
        if other is primary:
            continue
        if other.kind == rtype:
            fx.notices.append(
                f"You attached more than one {DOC_TYPE_LABELS[ex.doc_type]}; I used "
                f"{primary.name}. Please check the values."
            )
        elif other.kind is not None:
            fx.notices.append(
                f"I ignored {other.name} for the values; send it separately if it is another "
                "request."
            )
    unreadable = {
        _UNREADABLE_ALIASES.get(n.strip().lower(), n.strip().lower()) for n in ex.unreadable_fields
    }
    values = _document_values(rtype, ex)
    expected = (
        ("start_date", "end_date") if rtype == RequestType.LEAVE else ("amount", "receipt_date")
    )
    updates: dict[str, object] = {}
    for name, doc_value in values.items():
        if name in unreadable:
            doc_value = None
        typed_value = getattr(typed, name)
        existing = getattr(draft, name)
        if doc_value is None:
            if name in expected and typed_value is None and existing is None:
                fx.unread[name] = primary.filename
            continue
        if typed_value is not None:
            if norm(name, typed_value) != norm(name, doc_value):
                fx.conflicts[name] = norm(name, doc_value) or ""
            else:
                fx.sourced.add(name)
        elif existing is not None and not update_mode:
            if norm(name, existing) != norm(name, doc_value):
                fx.conflicts[name] = norm(name, doc_value) or ""
        else:
            if (
                update_mode
                and existing is not None
                and norm(name, existing) == norm(name, doc_value)
            ):
                continue  # the request already has this value: nothing to change or tag
            updates[name] = doc_value
            fx.sourced.add(name)
    fx.fields = typed.model_copy(update=updates)
    if "end_date" in fx.unread and ex.days_advised is not None and ex.days_advised > 0:
        fx.days_advised = ex.days_advised
    if ex.person_name and not name_matches(user_name, ex.person_name):
        fx.warnings.append(
            f"The name on the document ({scrub(ex.person_name, 60)}) differs from your name; "
            "your approver will see this."
        )
    if ex.confidence is not None and ex.confidence < LOW_CONFIDENCE:
        fx.warnings.append(
            "The AI was not confident about reading this document; please check every value."
        )
    return fx


def cap_attachments(
    session: Session,
    conv: ConversationState,
    rtype: RequestType,
    candidates: list[int],
    notices: list[str],
) -> None:
    """Add ``candidates`` to the draft's attachments (accumulating, at most 3 per request)."""
    used = len(conv.attachment_ids)
    if conv.editing_request_id is not None:
        used += _linked_count(session, rtype, conv.editing_request_id)
    for attachment_id in candidates:
        if attachment_id in conv.attachment_ids:
            continue
        if used >= MAX_REQUEST_ATTACHMENTS:
            notices.append(
                f"A request can carry at most {MAX_REQUEST_ATTACHMENTS} documents, so I did "
                "not add another one."
            )
            break
        conv.attachment_ids.append(attachment_id)
        used += 1


# --- follow-up questions and card helpers -----------------------------------------------------
def unread_question(
    field_name: str, filename: str, *, start_date: date | None, days_advised: float | None
) -> str | None:
    """The deterministic question for something a document should have carried."""
    name = scrub(filename, 60)
    if field_name == "amount":
        return f"I could not read the total amount on {name}. How much is the claim, in HKD?"
    if field_name == "receipt_date":
        return f"I could not read the receipt date on {name}. What date is on the receipt?"
    if field_name == "start_date":
        return (
            f"I could not read the first day of rest on {name}. What is the first day of your "
            "leave? For example 2026-09-24."
        )
    if field_name == "end_date":
        if days_advised is not None and start_date is not None:
            days = plural(Decimal(str(days_advised)), "day")
            return (
                f"On {name} the certificate advises {days} of rest from "
                f"{start_date.isoformat()} but I could not see the last day. What is the last day?"
            )
        return (
            f"I could not read the last day of rest on {name}. What is the last day of your "
            "leave? If it is a single day, give me the same date again."
        )
    return None


def _display(name: str, value: str, values: dict[str, str | None]) -> str:
    if name in ("start_date", "end_date", "receipt_date"):
        return fmt_date(date.fromisoformat(value))
    if name == "amount":
        return fmt_money(Decimal(value), values.get("currency") or "HKD")
    return value.title() if name in ("leave_type", "claim_type") else value


def document_warnings(conv: ConversationState, values: dict[str, str | None]) -> list[str]:
    """Card warnings for the draft: name / confidence notes plus every field where the user's
    value still differs from the document's."""
    out = list(conv.doc_warnings)
    for name, doc_value in conv.doc_conflicts.items():
        current = values.get(name)
        if current is None or current == doc_value:
            continue
        label = FIELD_LABELS.get(name, name)
        out.append(
            f"{label}: you gave {_display(name, current, values)}, but the document shows "
            f"{_display(name, doc_value, values)}. I kept your value; nothing was overwritten."
        )
    return out


def document_card_fields(conv: ConversationState) -> set[str]:
    """Card field keys whose value came from a document."""
    return set(conv.sources)


def attachment_infos(session: Session, ids: list[int], owner_id: int) -> list[AttachmentInfo]:
    if not ids:
        return []
    rows = {
        row.id: row
        for row in session.scalars(
            select(Attachment).where(Attachment.id.in_(ids), Attachment.owner_user_id == owner_id)
        )
    }
    return [to_info(rows[i]) for i in ids if i in rows]
