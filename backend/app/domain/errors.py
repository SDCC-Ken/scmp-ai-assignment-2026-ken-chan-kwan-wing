"""Typed domain errors. Routes/services map these to HTTP responses."""


class DomainError(Exception):
    """Base class for every business-rule violation."""


class InvalidTransitionError(DomainError):
    """The requested status change is not an edge of the state machine."""

    def __init__(self, from_status: str, to_status: str) -> None:
        super().__init__(f"Invalid status transition: {from_status} -> {to_status}")
        self.from_status = from_status
        self.to_status = to_status


class NotAuthorizedError(DomainError):
    """The actor may not perform the action (wrong role, inactive, or self-review)."""


class LeaveCalculationError(DomainError):
    """Leave dates / day parts are invalid or cover no working day."""
