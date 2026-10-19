"""Application-owned, frozen calendar context for relative-time tool requests."""

import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


def freeze_clock(zone: str, timestamp: float | None = None) -> dict[str, str]:
    instant = datetime.fromtimestamp(time.time() if timestamp is None else timestamp, UTC)
    local = instant.astimezone(ZoneInfo(zone))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return {
        "timezone": zone,
        "request_at": local.isoformat(),
        "request_at_utc": instant.isoformat(),
        "today": local.date().isoformat(),
        "today_start": start.isoformat(),
        "today_end_exclusive": end.isoformat(),
        "today_start_utc": start.astimezone(UTC).isoformat(),
        "today_end_exclusive_utc": end.astimezone(UTC).isoformat(),
    }
