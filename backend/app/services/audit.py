"""Audit trail, external-submission and notification writers (validate polymorphic refs)."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditEvent, ExternalSubmission, Notification
from app.domain.enums import RequestType, SubmissionStatus
from app.services.references import ensure_entity_exists, ensure_request_exists


def record_audit(
    session: Session,
    *,
    entity_type: str,
    entity_id: int | None,
    event_type: str,
    actor_user_id: int | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> AuditEvent:
    """Add an audit row to the session (caller commits). Never pass tokens or secrets."""
    ensure_entity_exists(session, entity_type, entity_id)
    event = AuditEvent(
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        from_status=str(from_status) if from_status is not None else None,
        to_status=str(to_status) if to_status is not None else None,
        metadata_json=_jsonable(metadata or {}),
    )
    if created_at is not None:
        event.created_at = created_at
    session.add(event)
    return event


def record_external_submission(
    session: Session,
    *,
    request_type: RequestType,
    request_id: int,
    status: SubmissionStatus,
    http_status: int | None = None,
    external_reference_id: str | None = None,
    response_summary: dict[str, Any] | None = None,
    error_message: str | None = None,
    submitted_at: datetime | None = None,
    provider: str = "reqres",
) -> ExternalSubmission:
    ensure_request_exists(session, request_type, request_id)
    row = ExternalSubmission(
        request_type=request_type,
        request_id=request_id,
        provider=provider,
        status=status,
        http_status=http_status,
        external_reference_id=external_reference_id,
        response_summary_json=_jsonable(response_summary or {}),
        error_message=error_message,
    )
    if submitted_at is not None:
        row.submitted_at = submitted_at
    session.add(row)
    return row


def create_notification(
    session: Session,
    *,
    recipient_user_id: int,
    event_type: str,
    request_type: RequestType,
    request_id: int,
    read_at: datetime | None = None,
    created_at: datetime | None = None,
) -> Notification:
    ensure_request_exists(session, request_type, request_id)
    row = Notification(
        recipient_user_id=recipient_user_id,
        event_type=event_type,
        request_type=request_type,
        request_id=request_id,
        read_at=read_at,
    )
    if created_at is not None:
        row.created_at = created_at
    session.add(row)
    return row


def _jsonable(value: Any) -> Any:
    """Make metadata JSON-safe (Decimals become strings so no precision is lost)."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
