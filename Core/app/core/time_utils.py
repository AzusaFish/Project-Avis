"""Time helpers shared by routes/tools/agent loop."""

from __future__ import annotations

from datetime import datetime


# Return the current local time with timezone.
def now_local() -> datetime:
    return datetime.now().astimezone()


# Format local time as a human-readable timestamp.
def format_now_local(dt: datetime | None = None) -> str:
    value = dt or now_local()
    return value.strftime("%Y-%m-%d %H:%M:%S %z")


# Prefix text with a local timestamp token.
def prepend_user_time(text: str, dt: datetime | None = None) -> str:
    ts = format_now_local(dt)
    return f"[TIME {ts}] {text}"


# Build a payload with local time fields for tools.
def now_payload(dt: datetime | None = None) -> dict[str, str | int]:
    value = dt or now_local()
    return {
        "local_time": format_now_local(value),
        "iso": value.isoformat(),
        "unix": int(value.timestamp()),
    }

