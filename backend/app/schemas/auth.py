from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import UserRole


class UserPublic(BaseModel):
    """Never includes ``google_subject``."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    role: UserRole


class LoginRequest(BaseModel):
    # Plain str (not EmailStr): a malformed address is simply an unknown user -> 401, so
    # the endpoint gives the same answer for every failure.
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return value.strip().lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic
