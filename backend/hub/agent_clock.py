"""Application-owned, frozen calendar context for relative-time tool requests."""

import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


def freeze_clock(zone: str, timestamp: float | None = None) -> dict[str, str]:
    instant = datetime.fromtimestamp(time.time() if timestamp is None else timestamp, UTC)
    local = instant.astimezone(ZoneInfo(zone))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    week_start = start - timedelta(days=start.weekday())
    week_end = week_start + timedelta(days=7)
    return {
        "timezone": zone,
        "request_at": local.isoformat(),
        "request_at_utc": instant.isoformat(),
        "today": local.date().isoformat(),
        "today_start": start.isoformat(),
        "today_end_exclusive": end.isoformat(),
        "today_start_utc": start.astimezone(UTC).isoformat(),
        "today_end_exclusive_utc": end.astimezone(UTC).isoformat(),
        "week_start": week_start.isoformat(),
        "week_end_exclusive": week_end.isoformat(),
        "week_start_utc": week_start.astimezone(UTC).isoformat(),
        "week_end_exclusive_utc": week_end.astimezone(UTC).isoformat(),
    }
