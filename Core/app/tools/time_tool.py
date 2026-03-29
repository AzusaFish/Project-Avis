"""Tool that returns the current local time."""

from __future__ import annotations

from app.core.time_utils import now_payload


class CurrentTimeTool:
    """Simple tool callable by the planner when time info is needed."""

    name = "time_now"

    async def call(self, args: dict) -> str:
        payload = now_payload()
        return (
            f"local_time={payload['local_time']}, "
            f"iso={payload['iso']}, "
            f"unix={payload['unix']}"
        )

