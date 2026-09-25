"""Confirmation-card builders (UI payloads, kept apart from workflow state and DB models)."""

import secrets
from datetime import date
from decimal import Decimal

from app.chat.format import fmt_date, fmt_date_with_part, fmt_days, fmt_money
from app.chat.state import CardAction
from app.domain.enums import DayPart, RequestType
from app.schemas.chat import AttachmentInfo, CardField, CardInfoLine, ConfirmationCard

_LABELS = {
    "employee_email": "Employee",
    "leave_type": "Leave type",
    "start_date": "Start",
    "end_date": "End",
    "working_days": "Working days",
    "claim_type": "Claim type",
    "amount": "Amount",
    "receipt_date": "Receipt date",
    "status": "Current status",
}
_TITLES = {
    "create": {"leave": "Confirm leave application", "claim": "Confirm staff claim"},
}
CONFIRM_LABELS = {
    "create": "Submit",
    "update": "Save changes",
    "cancel": "Cancel request",
    "retry": "Retry",
}


def new_card_id() -> str:
    return "c_" + secrets.token_hex(4)


def display_values(
    request_type: RequestType,
    values: dict[str, str | None],
    *,
    working_days: str | None = None,
    email: str | None = None,
    status_label: str | None = None,
) -> dict[str, str]:
    """Human-readable card values in display order (skips what is not known)."""
    out: dict[str, str] = {}
    if email:
        out["employee_email"] = email
    if request_type == RequestType.LEAVE:
        if values.get("leave_type"):
            out["leave_type"] = str(values["leave_type"]).title()
        if values.get("start_date"):
            out["start_date"] = fmt_date_with_part(
                date.fromisoformat(str(values["start_date"])),
                DayPart(values.get("start_day_part") or "full"),
            )
        if values.get("end_date"):
            out["end_date"] = fmt_date_with_part(
                date.fromisoformat(str(values["end_date"])),
                DayPart(values.get("end_day_part") or "full"),
            )
        if working_days is not None:
            out["working_days"] = working_days
    else:
        if values.get("claim_type"):
            out["claim_type"] = str(values["claim_type"]).title()
        if values.get("amount") is not None:
            out["amount"] = fmt_money(
                Decimal(str(values["amount"])), values.get("currency") or "HKD"
            )
        if values.get("receipt_date"):
            out["receipt_date"] = fmt_date(date.fromisoformat(str(values["receipt_date"])))
    if status_label:
        out["status"] = status_label
    return out


def working_days_text(value: Decimal) -> str:
    return fmt_days(value)


def build_card(
    *,
    action: CardAction,
    request_type: RequestType,
    request_id: int | None,
    new: dict[str, str],
    old: dict[str, str] | None = None,
    warnings: list[str] | None = None,
    card_id: str | None = None,
    document_fields: set[str] | None = None,
    attachments: list[AttachmentInfo] | None = None,
    info: list[CardInfoLine] | None = None,
) -> ConfirmationCard:
    """``old`` (update cards) marks each changed field with its previous value.

    ``document_fields`` are the card field keys whose value was read from a document (tagged
    ``source="document"``); ``attachments`` are the files that will be linked on Confirm."""
    fields: list[CardField] = []
    for key, value in new.items():
        previous = old.get(key) if old is not None else None
        fields.append(
            CardField(
                key=key,
                label=_LABELS[key],
                value=value,
                old_value=previous if previous is not None and previous != value else None,
                source="document" if document_fields and key in document_fields else None,
            )
        )
    noun = "leave request" if request_type == RequestType.LEAVE else "claim"
    if action == "create":
        title = _TITLES["create"][request_type.value]
    elif action == "update":
        title = f"Confirm changes to {noun} #{request_id}"
    elif action == "cancel":
        title = f"Confirm cancellation of {noun} #{request_id}"
    else:
        title = f"Retry submission of {noun} #{request_id}"
    return ConfirmationCard(
        card_id=card_id or new_card_id(),
        action=action,
        request_type=request_type,
        request_id=request_id,
        title=title,
        fields=fields,
        warnings=warnings or [],
        info=info or [],
        state="open",
        confirm_label=CONFIRM_LABELS[action],  # type: ignore[arg-type]
        attachments=attachments or [],
    )
