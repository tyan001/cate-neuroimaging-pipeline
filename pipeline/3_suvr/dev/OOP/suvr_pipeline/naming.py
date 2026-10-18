"""Scan filename parsing: ``<subject>-<YYYYMMDD>_<modality>[_<extra>].nii``."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

DATE_FORMAT = "%Y%m%d"


@dataclass(frozen=True)
class ScanFile:
    """A NIfTI scan whose name encodes subject, date, modality and optional extra info.

    Examples:
        900004-20150527_PET.nii        -> ("900004", "20150527", "PET", None)
        900001-20240809_PET_256.nii    -> ("900001", "20240809", "PET", "256")
        900004-20090603_T1w.nii        -> ("900004", "20090603", "T1w", None)
    """

    path: Path
    subject_id: str
    date: str
    modality: str
    extra: Optional[str] = None

    @classmethod
    def parse(cls, path: Path) -> "ScanFile":
        path = Path(path)
        base = path.name.replace(".nii", "")
        subject_id, sep, rest = base.partition("-")
        parts = rest.split("_")
        if not sep or len(parts) < 2:
            raise ValueError(
                f"Invalid filename format: {path.name}. "
                "Expected format: subjID-scandate_modality[_info].nii"
            )
        extra = "_".join(parts[2:]) or None
        return cls(path, subject_id, parts[0], parts[1], extra)

    @classmethod
    def try_parse(cls, path: Path) -> Optional["ScanFile"]:
        try:
            return cls.parse(path)
        except ValueError:
            return None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def acquired(self) -> datetime:
        """Scan date as a datetime; raises ValueError if the date field is not YYYYMMDD."""
        return datetime.strptime(self.date, DATE_FORMAT)

    @property
    def is_cormprage(self) -> bool:
        return "CorMPRAGE" in self.path.name

    def with_extra(self, prefix: str) -> str:
        """``prefix`` followed by ``_<extra>`` when this scan has extra info."""
        return f"{prefix}_{self.extra}" if self.extra else prefix
