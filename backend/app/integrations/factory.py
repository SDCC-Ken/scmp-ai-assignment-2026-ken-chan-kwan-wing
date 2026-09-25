"""Build the configured submission adapter."""

from app.config import Settings
from app.integrations.base import SubmissionAdapter


def build_submission_adapter(settings: Settings) -> SubmissionAdapter:
    """``reqres`` (the hosted mock API, default) or ``fake`` (offline/tests only)."""
    name = settings.submission_provider.strip().lower()
    if name == "reqres":
        from app.integrations.reqres import ReqresSubmissionAdapter

        return ReqresSubmissionAdapter(settings)
    if name == "fake":
        from app.integrations.fake import FakeSubmissionAdapter

        return FakeSubmissionAdapter()
    raise ValueError(
        f"Unsupported SUBMISSION_PROVIDER {settings.submission_provider!r}; use 'reqres' or 'fake'"
    )
