"""Stand-ins used when a real provider cannot be built (missing key, bad config).

They keep the API up: the chat then answers with a graceful "AI service unavailable" message
and submissions are saved as ``submission_failed`` so the user can retry later.
"""

from collections.abc import Sequence

from app.integrations.base import ClaimSubmissionPayload, LeaveSubmissionPayload, SubmissionResult
from app.llm.base import LLMError
from app.llm.schemas import AgentTurn, AttachmentInput, LLMContext


class UnavailableLLM:
    name = "unavailable"
    model = "none"

    def analyse(
        self,
        user_message: str,
        context: LLMContext,
        attachments: Sequence[AttachmentInput] = (),
    ) -> AgentTurn:
        raise LLMError("The LLM provider is not configured or could not be created")


class UnavailableAdapter:
    provider = "unavailable"

    def _fail(self) -> SubmissionResult:
        return SubmissionResult(
            ok=False, error_message="The submission service is not configured on this server."
        )

    def submit_leave(self, payload: LeaveSubmissionPayload) -> SubmissionResult:
        return self._fail()

    def submit_claim(self, payload: ClaimSubmissionPayload) -> SubmissionResult:
        return self._fail()
