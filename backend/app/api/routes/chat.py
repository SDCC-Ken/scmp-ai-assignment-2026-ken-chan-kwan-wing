"""Employee chat endpoints (mounted under /api/chat). Contract: docs/chat-api-contract.md."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_llm_provider, get_submission_adapter
from app.auth.dependencies import require_chat_access
from app.chat.actions import StaleCardError
from app.chat.inbox import InboxActionInvalid, InboxConflict
from app.chat.service import ChatService, ConversationConflict, ConversationNotFound
from app.db.models import User
from app.db.session import get_db
from app.integrations.base import SubmissionAdapter
from app.llm.base import LLMProvider
from app.schemas.chat import (
    ActionBody,
    ConversationDetail,
    ConversationList,
    ConversationSummary,
    InboxEmpty,
    InboxOpened,
    MessageBody,
    TurnResponse,
)
from app.services.attachments import AttachmentError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])
# Users who can file requests OR decide a queue (Phase 3: approvers use the bell inbox).
ChatUser = Depends(require_chat_access)


def get_chat_service(
    request: Request,
    db: Session = Depends(get_db),
    user: User = ChatUser,
    llm: LLMProvider = Depends(get_llm_provider),
    adapter: SubmissionAdapter = Depends(get_submission_adapter),
) -> ChatService:
    return ChatService(db, user, llm, adapter, request.app.state.settings)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")


def _db_unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "The database is temporarily unavailable. Please try again."},
    )


@router.get("/conversations", response_model=ConversationList)
def list_conversations(service: ChatService = Depends(get_chat_service)) -> ConversationList:
    return ConversationList(items=service.list_conversations())


@router.post(
    "/conversations", response_model=ConversationSummary, status_code=status.HTTP_201_CREATED
)
def create_conversation(service: ChatService = Depends(get_chat_service)) -> ConversationSummary:
    return service.create_conversation()


@router.post(
    "/inbox",
    response_model=None,
    responses={
        200: {"model": InboxEmpty, "description": "Nothing to handle; no conversation created."},
        201: {"model": InboxOpened, "description": "A new conversation with the first card."},
    },
)
def open_inbox(service: ChatService = Depends(get_chat_service)) -> JSONResponse:
    """The bell: start a new "Items to handle (N)" conversation (docs/inbox-design.md)."""
    try:
        opened = service.open_inbox()
    except SQLAlchemyError:
        logger.exception("Database error while opening the inbox")
        return _db_unavailable()
    code = status.HTTP_200_OK if isinstance(opened, InboxEmpty) else status.HTTP_201_CREATED
    return JSONResponse(status_code=code, content=opened.model_dump(mode="json"))


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: int, service: ChatService = Depends(get_chat_service)
) -> ConversationDetail:
    try:
        return service.get_conversation(conversation_id)
    except ConversationNotFound:
        raise _not_found() from None


@router.post("/conversations/{conversation_id}/messages", response_model=TurnResponse)
def post_message(
    conversation_id: int,
    body: MessageBody,
    request: Request,
    service: ChatService = Depends(get_chat_service),
) -> Response | TurnResponse:
    limit = request.app.state.settings.chat_max_message_chars
    if len(body.content) > limit:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Message is too long (maximum {limit} characters).",
        )
    max_files = request.app.state.settings.max_attachments_per_message
    if len(body.attachment_ids) > max_files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"At most {max_files} files can be sent with one message.",
        )
    if not body.content.strip() and not body.attachment_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Message must not be blank."
        )
    try:
        return service.post_message(conversation_id, body.content, body.attachment_ids)
    except ConversationNotFound:
        raise _not_found() from None
    except AttachmentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    except ConversationConflict:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "The conversation changed while I was working. Please try again."},
        )
    except SQLAlchemyError:
        logger.exception("Database error while handling a chat message")
        return _db_unavailable()


@router.post("/conversations/{conversation_id}/actions", response_model=TurnResponse)
def post_action(
    conversation_id: int,
    body: ActionBody,
    service: ChatService = Depends(get_chat_service),
) -> Response | TurnResponse:
    try:
        return service.post_action(
            conversation_id, body.card_id, body.action, body.note, body.confirmed
        )
    except ConversationNotFound:
        raise _not_found() from None
    except InboxActionInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None
    except InboxConflict:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "The conversation changed while I was working. Please try again."},
        )
    except StaleCardError as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc), "warning_code": "stale_card"},
        )
    except SQLAlchemyError:
        logger.exception("Database error while handling a card action")
        return _db_unavailable()
