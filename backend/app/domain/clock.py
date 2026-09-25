"""Clock helpers. Hong Kong has no DST, so a fixed UTC+8 offset avoids a tzdata dependency."""

from datetime import UTC, date, datetime, timedelta, timezone

HK_TZ = timezone(timedelta(hours=8), "HKT")


def utcnow() -> datetime:
    return datetime.now(UTC)


def today_hk() -> date:
    return datetime.now(HK_TZ).date()
