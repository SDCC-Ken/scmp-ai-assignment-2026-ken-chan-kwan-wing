from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import UserRole


class DepartmentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class UserPublic(BaseModel):
    """Never includes ``google_subject``. ``can_request`` (has an approver configured: may use
    the chat) and ``approves`` (which queue the user decides) are derived from the user."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    role: UserRole
    department: DepartmentPublic | None = None
    job_title: str | None = None
    can_request: bool
    approves: Literal["leave", "claim"] | None = None


class LoginRequest(BaseModel):
    # Plain str (not EmailStr): a malformed address is simply an unknown user -> 401, so
    # the endpoint gives the same answer for every failure.
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return value.strip().lower()


class LoginResponse(BaseModel):
    """Login body. The JWT is delivered only as an httpOnly cookie, never in the body."""

    expires_in: int
    user: UserPublic
