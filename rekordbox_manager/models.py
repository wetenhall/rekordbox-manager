from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math


@dataclass(frozen=True)
class Cue:
    time: float
    label: str
    kind: str = "memory"
    end: float | None = None


@dataclass
class Grid:
    times: list[float]
    positions: list[int]

    def validate(self) -> None:
        if len(self.times) < 2 or len(self.times) != len(self.positions):
            raise ValueError("No usable beat grid. Analyse this track in Rekordbox first.")
        if any(not math.isfinite(t) or t < 0 for t in self.times):
            raise ValueError("Grid contains invalid timestamps.")
        if any(b <= a for a, b in zip(self.times, self.times[1:])):
            raise ValueError("Grid timestamps must increase.")
        if any(p not in (1, 2, 3, 4) for p in self.positions):
            raise ValueError("Only 4/4 grids are supported in this build.")
        if any(b != a % 4 + 1 for a, b in zip(self.positions, self.positions[1:])):
            raise ValueError("Grid contains a bar-position discontinuity; review in Rekordbox.")

    def nearest_downbeat(self, time: float) -> int:
        self.validate()
        candidates = [i for i, p in enumerate(self.positions) if p == 1]
        if not candidates:
            raise ValueError("No bar downbeats in this grid.")
        return min(candidates, key=lambda i: abs(self.times[i] - time))


@dataclass
class Track:
    id: str
    title: str
    artist: str
    genre: str
    path: Path
    duration: float
    bpm: float
    grid: Grid
    cues: list[Cue] = field(default_factory=list)
    analysis_paths: list[Path] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Options:
    fix_grid: bool = False
    set_cues: bool = True
    replace_memory: bool = False


@dataclass
class Proposal:
    track: Track
    options: Options
    grid: Grid
    cues: list[Cue]
    first_drop: float | None = None
    second_drop: float | None = None
    warnings: list[str] = field(default_factory=list)
    peaks: list[float] = field(default_factory=list)
    grid_note: str = "Existing grid retained"
    reviewed: bool = False
    error: str = ""
    grid_approved: bool = False
    cues_dirty: bool = False
    applied: bool = False

    @property
    def ready_to_apply(self) -> bool:
        return not self.error and not self.cues_dirty and not self.applied and (self.options.fix_grid or self.options.set_cues)

    @property
    def can_apply(self) -> bool:
        return self.ready_to_apply and self.reviewed and (not self.options.fix_grid or self.grid_approved)
