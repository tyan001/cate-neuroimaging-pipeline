"""Amyloid tracers, their Centiloid equations, and how a scan's tracer is chosen."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .naming import DATE_FORMAT


@dataclass(frozen=True)
class Tracer:
    name: str
    slope: float
    intercept: float

    def centiloid(self, global_suvr: float) -> float:
        return self.slope * global_suvr - self.intercept


AMYVID = Tracer("Amyvid", 183.07, 177.26)      # 18F-florbetapir
NEURACEQ = Tracer("Neuraceq", 153.4, 154.9)    # 18F-florbetaben
TRACERS = {t.name.lower(): t for t in (AMYVID, NEURACEQ)}


@dataclass(frozen=True)
class TracerPolicy:
    """Site switched Amyvid -> Neuraceq on ``cutoff``; ``override`` forces one tracer for every scan.

    Per-subject exceptions are not modelled -- run those subjects with an override.
    """

    cutoff: datetime = datetime(2016, 9, 27)
    override: Optional[Tracer] = None

    @classmethod
    def from_name(cls, name: Optional[str]) -> "TracerPolicy":
        return cls(override=TRACERS[name.lower()] if name else None)

    def for_date(self, scan_date: str) -> Tracer:
        if self.override:
            return self.override
        return NEURACEQ if datetime.strptime(scan_date, DATE_FORMAT) >= self.cutoff else AMYVID
