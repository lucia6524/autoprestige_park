from datetime import datetime, timezone


def utc_now_naive() -> datetime:
    """Return the current UTC time without tzinfo for naive DB columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_utc_naive(value: datetime) -> datetime:
    """Convert an aware or naive datetime to naive UTC for DB columns."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.replace(tzinfo=None)