from typing import Any

import pytest

from app.config import Settings
from app.integrations.factory import build_submission_adapter
from app.integrations.fake import FakeSubmissionAdapter
from app.integrations.reqres import ReqresSubmissionAdapter


def settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)


def test_reqres_is_default_and_builds_without_key() -> None:
    adapter = build_submission_adapter(settings())
    assert isinstance(adapter, ReqresSubmissionAdapter)
    assert adapter.provider == "reqres"


def test_fake() -> None:
    adapter = build_submission_adapter(settings(submission_provider="fake"))
    assert isinstance(adapter, FakeSubmissionAdapter)
    assert adapter.provider == "fake"


def test_case_insensitive() -> None:
    assert isinstance(
        build_submission_adapter(settings(submission_provider=" ReqRes ")), ReqresSubmissionAdapter
    )


def test_unknown_is_a_config_error() -> None:
    with pytest.raises(ValueError, match="SUBMISSION_PROVIDER"):
        build_submission_adapter(settings(submission_provider="webhook"))
