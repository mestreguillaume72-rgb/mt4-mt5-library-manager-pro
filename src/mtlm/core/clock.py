"""Horloge injectable : le code métier ne lit jamais l'heure directement,
ce qui rend les tests déterministes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Instant courant, toujours en UTC."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Horloge figée, avançable manuellement (tests)."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FixedClock exige une date avec fuseau (UTC)")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


def iso_utc(moment: datetime) -> str:
    """Horodatage ISO 8601 UTC à la milliseconde, ex. ``2026-11-10T20:14:29.123Z``."""
    utc = moment.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"
