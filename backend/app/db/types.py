"""Column types that keep SQLite round-trips exact."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes.

    SQLite drops tzinfo, so values are normalised to UTC on the way in (naive values are
    rejected, not guessed) and re-attached as UTC on the way out.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Naive datetime is not allowed; use a timezone-aware datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class ScaledDecimal(TypeDecorator[Decimal]):
    """Exact decimals stored as INTEGER (value * 10**places); never a float.

    SQLite has no decimal type, and SQLAlchemy's Numeric would silently round-trip through
    float. Integers keep ordering/aggregation correct and precision exact. Values with
    more decimal places than ``places`` are rejected rather than rounded.
    """

    impl = BigInteger
    cache_ok = True

    def __init__(self, places: int) -> None:
        super().__init__()
        self.places = places

    def process_bind_param(self, value: Decimal | int | None, dialect: Dialect) -> int | None:
        if value is None:
            return None
        if isinstance(value, float) or not isinstance(value, Decimal | int):
            raise TypeError("Use Decimal (not float) for exact decimal columns")
        scaled = Decimal(value) * (Decimal(10) ** self.places)
        if scaled != scaled.to_integral_value():
            raise ValueError(f"More than {self.places} decimal places: {value}")
        return int(scaled)

    def process_result_value(self, value: int | None, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return (Decimal(value) / (Decimal(10) ** self.places)).quantize(
            Decimal(1).scaleb(-self.places)
        )
