"""Time abstraction. Strategy layer MUST go through this, never datetime.now()."""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
UTC = ZoneInfo("UTC")


class Clock(ABC):
    @abstractmethod
    def now_utc(self) -> dt.datetime: ...

    def now_local(self, tz: ZoneInfo = TAIPEI) -> dt.datetime:
        return self.now_utc().astimezone(tz)


class SystemClock(Clock):
    def now_utc(self) -> dt.datetime:
        return dt.datetime.now(tz=UTC)


class FixedClock(Clock):
    """For backtests / tests — caller advances time explicitly."""

    def __init__(self, start: dt.datetime):
        if start.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._now = start.astimezone(UTC)

    def now_utc(self) -> dt.datetime:
        return self._now

    def advance(self, delta: dt.timedelta) -> None:
        self._now = self._now + delta

    def set(self, ts: dt.datetime) -> None:
        self._now = ts.astimezone(UTC)
