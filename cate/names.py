"""Scan names and SUVR folder names. Pure functions: no filesystem access.

    scan              <subject>-<YYYYMMDD>_<type>[_<extra>].nii    990002-20250519_PET_256.nii
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

DATE_FORMAT = "%Y%m%d"
NII = ".nii"
CORMPRAGE = "CorMPRAGE"
CORMPRAGE_SUFFIX = "_" + CORMPRAGE

_DATE_RE = re.compile(r"\d{8}")


class NameParseError(ValueError):
    """A scan or folder name that does not follow the ADRC naming format."""


def _parse_date(text: str, name: str) -> date:
    if not _DATE_RE.fullmatch(text):
        raise NameParseError(f"{name}: date {text!r} is not eight digits (YYYYMMDD)")
    try:
        return datetime.strptime(text, DATE_FORMAT).date()
    except ValueError:
        raise NameParseError(f"{name}: date {text!r} is not a valid date") from None


@dataclass(frozen=True)
class ScanName:
    subject: str
    date: date
    scan_type: str
    extra: Optional[str] = None

    @property
    def stem(self) -> str:
        return _with_extra(f"{self.subject}-{self.date:{DATE_FORMAT}}_{self.scan_type}", self.extra)

    @property
    def filename(self) -> str:
        return self.stem + NII


def _with_extra(prefix: str, extra: Optional[str]) -> str:
    return f"{prefix}_{extra}" if extra else prefix


def parse_scan_name(filename: str) -> ScanName:
    """Read ``<subject>-<YYYYMMDD>_<type>[_<extra>].nii``; raise NameParseError otherwise."""
    expected = "expected <subject>-<YYYYMMDD>_<type>[_<extra>].nii"
    if not filename.endswith(NII):
        raise NameParseError(f"{filename}: not a .nii file, {expected}")
    subject, sep, rest = filename[: -len(NII)].partition("-")
    parts = rest.split("_")
    if not sep or not subject or "_" in subject or len(parts) < 2 or not all(parts):
        raise NameParseError(f"{filename}: {expected}")
    extra = "_".join(parts[2:]) or None
    return ScanName(subject, _parse_date(parts[0], filename), parts[1], extra)


def pet_folder_name(pet: ScanName) -> str:
    """The PET output folder under ``suvr/``: ``<subject>-<YYYYMMDD>_PET[_<extra>]``."""
    return _with_extra(f"{pet.subject}-{pet.date:{DATE_FORMAT}}_PET", pet.extra)


@dataclass(frozen=True)
class PairFolderName:
    """``<subject>_pet_<YYYYMMDD>[_<extra>]_mri_<YYYYMMDD>[_CorMPRAGE][_<extra>]``."""

    subject: str
    pet_date: date
    mri_date: date
    pet_extra: Optional[str] = None
    mri_cormprage: bool = False
    mri_extra: Optional[str] = None

    @property
    def name(self) -> str:
        pet_part = _with_extra(f"{self.subject}_pet_{self.pet_date:{DATE_FORMAT}}", self.pet_extra)
        mri_part = f"mri_{self.mri_date:{DATE_FORMAT}}" + (CORMPRAGE_SUFFIX if self.mri_cormprage else "")
        return _with_extra(f"{pet_part}_{mri_part}", self.mri_extra)

    @property
    def gap_days(self) -> int:
        return abs((self.mri_date - self.pet_date).days)


_PAIR_RE = re.compile(
    r"(?P<subject>[^_]+)_pet_(?P<pet_date>[^_]+)(?:_(?P<pet_extra>.+?))?"
    r"_mri_(?P<mri_date>[^_]+)(?P<cormprage>" + CORMPRAGE_SUFFIX + r")?(?:_(?P<mri_extra>.+))?"
)


def pair_folder_name(pet: ScanName, mri: ScanName) -> str:
    """The Pair folder name for ``pet`` paired with ``mri``, in the format prepare has always used."""
    return PairFolderName(
        subject=pet.subject,
        pet_date=pet.date,
        mri_date=mri.date,
        pet_extra=pet.extra,
        mri_cormprage=CORMPRAGE in mri.filename,
        mri_extra=mri.extra,
    ).name


def parse_pair_folder_name(name: str) -> PairFolderName:
    match = _PAIR_RE.fullmatch(name)
    if not match:
        raise NameParseError(
            f"{name}: expected <subject>_pet_<YYYYMMDD>[_<extra>]_mri_<YYYYMMDD>[_CorMPRAGE][_<extra>]"
        )
    return PairFolderName(
        subject=match["subject"],
        pet_date=_parse_date(match["pet_date"], name),
        mri_date=_parse_date(match["mri_date"], name),
        pet_extra=match["pet_extra"],
        mri_cormprage=bool(match["cormprage"]),
        mri_extra=match["mri_extra"],
    )


def parse_pet_folder_name(name: str) -> ScanName:
    """Read a PET output folder name, ``<subject>-<YYYYMMDD>_PET[_<extra>]``."""
    try:
        parsed = parse_scan_name(name + NII)
    except NameParseError:
        parsed = None
    if parsed is None or parsed.scan_type != "PET":
        raise NameParseError(f"{name}: expected <subject>-<YYYYMMDD>_PET[_<extra>]")
    return parsed
