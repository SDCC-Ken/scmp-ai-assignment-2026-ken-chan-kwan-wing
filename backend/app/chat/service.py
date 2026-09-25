"""Chat service: conversations, message turns and card actions for one signed-in employee."""

import logging
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.graph import Reply, TurnResult, run_turn
from app.chat.actions import ActionResult, CardActions, StaleCardError
from app.chat.policy import HISTORY_MESSAGE_CHARS, HISTORY_MESSAGES
from app.chat.state import ConversationState, load_state
from app.chat.store import (
    add_message,
    cas_save_state,
    make_title,
    message_out,
    set_card_state,
)
from app.chat.turn_input import ChatTurnDeps, build_attachment_inputs
from app.config import Settings, get_settings
from app.db.models import Attachment, Conversation, ConversationMessage, User
from app.domain import clock
from app.domain.enums import ConversationStatus, SenderType
from app.integrations.base import SubmissionAdapter
from app.llm.base import LLMProvider
from app.llm.schemas import ChatTurn
from app.schemas.chat import (
    ConversationDetail,
    ConversationSummary,
    Message,
    TraceStep,
    TurnResponse,
)
from app.services.attachments import (
    attach_to_message,
    attachments_by_message,
    load_staged,
    to_info,
)

logger = logging.getLogger(__name__)

EMPTY_HISTORY_TEXT = "(attached a document)"  # history entry of a message that had no text


class ConversationNotFound(Exception):
    """No such conversation for this user (also used for other users' conversations)."""


class ConversationConflict(Exception):
    """The conversation changed while this request was being processed (HTTP 409)."""


class ChatService:
    def __init__(
        self,
        session: Session,
        user: User,
        llm: LLMProvider,
        adapter: SubmissionAdapter,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.user = user
        self.llm = llm
        self.adapter = adapter
        self.settings = settings or get_settings()

    # ---- queries ------------------------------------------------------------------------------
    def _owned(self, conversation_id: int) -> Conversation:
        conv = self.session.get(Conversation, conversation_id)
        if conv is None or conv.user_id != self.user.id:
            raise ConversationNotFound
        return conv

    def _titles(self, conversation_ids: list[int]) -> dict[int, str | None]:
        if not conversation_ids:
            return {}
        first_ids = (
            select(func.min(ConversationMessage.id))
            .where(
                ConversationMessage.conversation_id.in_(conversation_ids),
                ConversationMessage.sender_type == SenderType.USER,
            )
            .group_by(ConversationMessage.conversation_id)
        )
        rows = self.session.execute(
            select(ConversationMessage.conversation_id, ConversationMessage.content).where(
                ConversationMessage.id.in_(first_ids)
            )
        ).all()
        titles: dict[int, str | None] = {cid: content for cid, content in rows}
        # A first message without text is titled after its first attachment.
        blank = [cid for cid, content in titles.items() if not (content or "").strip()]
        if blank:
            first_message_ids = {
                row.conversation_id: row.id
                for row in self.session.scalars(
                    select(ConversationMessage).where(ConversationMessage.id.in_(first_ids))
                )
            }
            for cid in blank:
                name = self.session.scalar(
                    select(Attachment.original_filename)
                    .where(Attachment.message_id == first_message_ids.get(cid))
                    .order_by(Attachment.id)
                    .limit(1)
                )
                if name:
                    titles[cid] = f"Attachment: {name}"
        return titles

    def _summaries(self, conversations: list[Conversation]) -> list[ConversationSummary]:
        first_messages = self._titles([c.id for c in conversations])
        out: list[ConversationSummary] = []
        for conv in conversations:
            state = load_state(conv.state_json, conv.active_request_type)
            out.append(
                ConversationSummary(
                    id=conv.id,
                    title=make_title(first_messages.get(conv.id)),
                    status=conv.status.value,
                    active_request_type=conv.active_request_type,
                    has_pending_card=state.open_card() is not None,
                    created_at=conv.created_at,
                    updated_at=conv.updated_at,
                )
            )
        return out

    def _summary(self, conv: Conversation) -> ConversationSummary:
        self.session.refresh(conv)
        return self._summaries([conv])[0]

    def list_conversations(self) -> list[ConversationSummary]:
        rows = self.session.scalars(
            select(Conversation)
            .where(Conversation.user_id == self.user.id)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        ).all()
        return self._summaries(list(rows))

    def create_conversation(self) -> ConversationSummary:
        conv = Conversation(user_id=self.user.id, status=ConversationStatus.ACTIVE)
        self.session.add(conv)
        self.session.commit()
        return self._summaries([conv])[0]

    def get_conversation(self, conversation_id: int) -> ConversationDetail:
        conv = self._owned(conversation_id)
        rows = list(
            self.session.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conv.id)
                .order_by(ConversationMessage.id)
            ).all()
        )
        return ConversationDetail(
            conversation=self._summaries([conv])[0],
            messages=self._messages_out(rows),
        )

    def _messages_out(self, rows: list[ConversationMessage]) -> list[Message]:
        files = attachments_by_message(
            self.session, [r.id for r in rows if r.sender_type == SenderType.USER]
        )
        return [message_out(r, files.get(r.id)) for r in rows]

    # ---- message turn ---------------------------------------------------------------------------
    def _history(self, conversation_id: int, before_id: int) -> list[ChatTurn]:
        rows = self.session.scalars(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.id < before_id,
                ConversationMessage.sender_type != SenderType.SYSTEM,
            )
            .order_by(ConversationMessage.id.desc())
            .limit(HISTORY_MESSAGES)
        ).all()
        return [
            ChatTurn(
                role=r.sender_type.value,  # type: ignore[arg-type]
                content=(r.content or EMPTY_HISTORY_TEXT)[:HISTORY_MESSAGE_CHARS],
            )
            for r in reversed(rows)
        ]

    def post_message(
        self, conversation_id: int, content: str, attachment_ids: list[int] | None = None
    ) -> TurnResponse:
        conv = self._owned(conversation_id)
        state = load_state(conv.state_json, conv.active_request_type)
        # Validate the files BEFORE anything is written: a bad id must not create a message.
        files = load_staged(self.session, self.user.id, conv.id, attachment_ids or [])

        # The user's message is saved first, so it survives any later failure.
        user_row = add_message(self.session, conv.id, SenderType.USER, content)
        attach_to_message(self.session, files, user_row.id)
        conv.status = ConversationStatus.ACTIVE
        conv.updated_at = clock.utcnow()
        self.session.commit()
        user_out = message_out(user_row, [to_info(f) for f in files])

        history = self._history(conv.id, before_id=user_row.id)
        deps = ChatTurnDeps(
            session=self.session,
            llm=self.llm,
            user_id=self.user.id,
            user_email=self.user.email,
            user_name=self.user.display_name,
            today=clock.today_hk(),
            attachments=build_attachment_inputs(files, self.settings.upload_dir),
        )
        started = time.perf_counter()
        try:
            result = run_turn(deps, state, content, history)
        except Exception:
            logger.exception("Chat turn failed unexpectedly")
            self.session.rollback()
            result = TurnResult(
                reply=Reply(
                    "Something went wrong on my side, so nothing was changed. "
                    "Please try again in a moment.",
                    warning_code="llm_unavailable",
                ),
                state=state,
                trace=[
                    TraceStep(
                        step="respond",
                        label="Turn failed",
                        detail="unexpected error; conversation left unchanged",
                        ok=False,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                    )
                ],
            )
        self.session.rollback()  # reads only so far; make sure no transaction is left open

        for attachment in files:  # what the provider read from each file (no bytes, no secrets)
            extraction = result.extractions.get(attachment.id)
            if extraction is not None:
                attachment.extraction_json = extraction
        for card_id in result.superseded:
            set_card_state(self.session, conv.id, card_id, "superseded")
        assistant_row = add_message(
            self.session,
            conv.id,
            SenderType.ASSISTANT,
            result.reply.text,
            ui=result.reply.ui,
            trace=result.trace,
        )
        if result.state_changed and not cas_save_state(
            self.session, conv.id, state.state_version, result.state
        ):
            self.session.rollback()
            raise ConversationConflict
        conv.updated_at = clock.utcnow()
        self.session.commit()

        return TurnResponse(
            conversation=self._summary(conv),
            user_message=user_out,
            assistant_messages=[message_out(assistant_row)],
            warning_code=result.reply.warning_code,  # type: ignore[arg-type]
        )

    # ---- card actions ------------------------------------------------------------------------
    def post_action(self, conversation_id: int, card_id: str, action: str) -> TurnResponse:
        conv = self._owned(conversation_id)
        state: ConversationState = load_state(conv.state_json, conv.active_request_type)
        card = state.open_card()
        if card is None or card.card_id != card_id:
            raise StaleCardError("This card is no longer active.")
        actions = CardActions(self.session, self.adapter, self.user, conv, clock.today_hk())
        result: ActionResult = (
            actions.discard(state, card) if action == "discard" else actions.confirm(state, card)
        )
        return TurnResponse(
            conversation=self._summary(conv),
            user_message=None,
            assistant_messages=[message_out(m) for m in result.messages],
            warning_code=result.warning_code,  # type: ignore[arg-type]
        )


__all__ = ["ChatService", "ConversationConflict", "ConversationNotFound", "StaleCardError"]
