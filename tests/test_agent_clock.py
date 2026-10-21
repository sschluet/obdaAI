from datetime import datetime

import pytest
from hub.agent_clock import freeze_clock
from hub.config import Settings
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("instant", "day", "hours"),
    [
        ("2026-10-18T23:30:00+00:00", "2026-10-19", 24),
        ("2026-03-29T12:00:00+00:00", "2026-03-29", 23),
        ("2026-10-25T12:00:00+00:00", "2026-10-25", 25),
    ],
)
def test_relative_day_uses_local_calendar_and_dst(instant, day, hours):
    frozen = freeze_clock("Europe/Berlin", datetime.fromisoformat(instant).timestamp())
    assert frozen["today"] == day
    begin = datetime.fromisoformat(frozen["today_start_utc"])
    end = datetime.fromisoformat(frozen["today_end_exclusive_utc"])
    assert (end - begin).total_seconds() == hours * 3600
    assert frozen["request_at_utc"] == instant


def test_agent_timezone_from_explicit_environment(monkeypatch):
    monkeypatch.setenv("HUB_AGENT_TIMEZONE", "America/New_York")
    cfg = Settings.from_env()
    assert cfg.agent_timezone == "America/New_York"
    frozen = freeze_clock(
        cfg.agent_timezone, datetime.fromisoformat("2026-10-19T01:00:00+00:00").timestamp()
    )
    assert frozen["today"] == "2026-10-18"


@pytest.mark.parametrize(
    ("instant", "monday", "hours"),
    [
        ("2026-10-20T12:00:00+00:00", "2026-10-19", 169),
        ("2026-03-29T12:00:00+00:00", "2026-03-23", 167),
        ("2026-10-18T23:30:00+00:00", "2026-10-19", 169),
    ],
)
def test_this_week_uses_local_monday_and_dst(instant, monday, hours):
    frozen = freeze_clock("Europe/Berlin", datetime.fromisoformat(instant).timestamp())
    assert frozen["week_start"].startswith(monday + "T00:00:00")
    begin = datetime.fromisoformat(frozen["week_start_utc"])
    end = datetime.fromisoformat(frozen["week_end_exclusive_utc"])
    assert (end - begin).total_seconds() == hours * 3600
    assert begin <= datetime.fromisoformat(instant) < end


def test_invalid_agent_timezone_rejected():
    with pytest.raises(ValidationError):
        Settings(agent_timezone="Not/A_Timezone")
