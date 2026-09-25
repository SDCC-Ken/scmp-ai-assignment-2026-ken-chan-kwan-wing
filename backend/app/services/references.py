"""Validation of polymorphic references (no DB foreign key can express them)."""

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ClaimRequest, Conversation, LeaveRequest, User
from app.domain.enums import RequestType

REQUEST_MODELS: dict[RequestType, type[LeaveRequest] | type[ClaimRequest]] = {
    RequestType.LEAVE: LeaveRequest,
    RequestType.CLAIM: ClaimRequest,
}

# audit_events.entity_type values -> model that must contain entity_id.
ENTITY_MODELS: dict[str, Any] = {
    "leave_request": LeaveRequest,
    "claim_request": ClaimRequest,
    "user": User,
    "conversation": Conversation,
}


class InvalidReferenceError(ValueError):
    """A polymorphic reference points at a row that does not exist / an unknown type."""


def ensure_request_exists(session: Session, request_type: RequestType, request_id: int) -> None:
    model = REQUEST_MODELS[RequestType(request_type)]
    if session.get(model, request_id) is None:
        raise InvalidReferenceError(f"{request_type} request {request_id} does not exist")


def ensure_entity_exists(session: Session, entity_type: str, entity_id: int | None) -> None:
    """Unknown entity types are rejected; ``entity_id=None`` is allowed (no entity)."""
    model = ENTITY_MODELS.get(entity_type)
    if model is None:
        raise InvalidReferenceError(f"Unknown entity type: {entity_type}")
    if entity_id is not None and session.get(model, entity_id) is None:
        raise InvalidReferenceError(f"{entity_type} {entity_id} does not exist")
