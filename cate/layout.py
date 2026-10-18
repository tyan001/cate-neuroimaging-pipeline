"""The ADRC tree, organised around the Session.

    <root>/<subject>/<YYYYMMDD>/anat/<subject>-<YYYYMMDD>_T1w.nii           MRI (or _CorMPRAGE)
    <root>/<subject>/<YYYYMMDD>/freesurfer741/<MRI stem>/                    recon folder
    <root>/<subject>/<YYYYMMDD>/pet/<subject>-<YYYYMMDD>_PET[_<extra>].nii   PET
    <root>/<subject>/<YYYYMMDD>/suvr/<PET folder>/<Pair folder>/             one Pair
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Tuple, Union

from .names import (
    DATE_FORMAT,
    NII,
    NameParseError,
    PairFolderName,
    ScanName,
    pair_folder_name,
    parse_pair_folder_name,
    parse_scan_name,
    pet_folder_name,
)

RECON_DIRNAME = "freesurfer741"
SUVR_DIRNAME = "suvr"
NOT_SUBJECTS = frozenset({"logs", "fs_logs"})
MRI_TYPES = ("T1w", "CorMPRAGE")  # in order of preference
ONE_YEAR_DAYS = 365  # inclusive: a PET 365 days from its MRI still pairs

_SESSION_RE = re.compile(r"\d{8}")


def _subfolders(path: Path) -> List[Path]:
    return sorted(p for p in path.iterdir() if p.is_dir())


class Dataset:
    """An ADRC root folder holding one folder per Subject."""

    def __init__(self, root: Union[str, Path]):
        self.root = Path(root)

    def subjects(self) -> List[Subject]:
        return [
            Subject(p) for p in _subfolders(self.root)
            if p.name not in NOT_SUBJECTS and not p.name.startswith(".")
        ]

    def problems(self) -> List[Problem]:
        """Every problem in every Subject."""
        return [problem for subject in self.subjects() for problem in subject.problems()]


@dataclass(frozen=True)
class Problem:
    """Something on disk that breaks a data rule, so it is left out of what the layout reports."""

    path: Path
    reason: str


class Subject:
    def __init__(self, path: Path):
        self.path = path

    @property
    def id(self) -> str:
        return self.path.name

    def sessions(self) -> List[Session]:
        """The Subject's valid Sessions, by date."""
        return [s for s in self._read_sessions() if isinstance(s, Session)]

    def problems(self) -> List[Problem]:
        """Sessions that break a data rule, then PETs whose two closest MRIs tie."""
        sessions_or_problems = self._read_sessions()
        sessions = [s for s in sessions_or_problems if isinstance(s, Session)]
        ties = [r.problem for r in _pair(sessions) if isinstance(r, Tie)]
        return [s for s in sessions_or_problems if isinstance(s, Problem)] + ties

    def pairings(self) -> List[PairingResult]:
        """One result for each PET in the Subject's valid Sessions, by PET date."""
        return _pair(self.sessions())

    def existing_pair_folders(self) -> List[ExistingPairFolder]:
        """Pair folders already on disk under any Session, valid or not, whatever their gap."""
        found = []
        for session in self._session_folders():
            suvr = session / SUVR_DIRNAME
            for pet_folder in _subfolders(suvr) if suvr.is_dir() else []:
                for folder in _subfolders(pet_folder):
                    try:
                        found.append(ExistingPairFolder(folder, parse_pair_folder_name(folder.name)))
                    except NameParseError:
                        pass  # logs/ and anything else that is not a Pair folder
        return found

    def _session_folders(self) -> List[Path]:
        return [p for p in _subfolders(self.path) if _SESSION_RE.fullmatch(p.name)]

    def _read_sessions(self) -> List[Union[Session, Problem]]:
        return [_read_session(p) for p in self._session_folders()]


@dataclass(frozen=True)
class Scan:
    """A ``.nii`` scan file and what its name says."""

    path: Path
    name: ScanName

    @property
    def session_folder(self) -> Path:
        """The Session folder holding this scan's ``anat/`` or ``pet/`` folder."""
        return self.path.parent.parent


@dataclass(frozen=True)
class Session:
    path: Path
    date: date
    mri: Optional[Scan]
    pet: Optional[Scan]

    @property
    def recon_folder(self) -> Optional[Path]:
        """``freesurfer741/<MRI stem>`` under this Session, or None without an MRI."""
        return _recon_folder(self.mri) if self.mri else None


@dataclass(frozen=True)
class Pair:
    """A PET matched with an MRI, and where its Pair folder goes."""

    pet: Scan
    mri: Scan

    @property
    def gap_days(self) -> int:
        return _gap_days(self.pet, self.mri)

    @property
    def recon_folder(self) -> Path:
        return _recon_folder(self.mri)

    @property
    def folder_name(self) -> str:
        return pair_folder_name(self.pet.name, self.mri.name)

    @property
    def folder(self) -> Path:
        """``<PET Session>/suvr/<PET folder>/<Pair folder>``."""
        return self.pet.session_folder / SUVR_DIRNAME / pet_folder_name(self.pet.name) / self.folder_name


@dataclass(frozen=True)
class OverOneYear:
    """A PET whose closest MRI is more than ONE_YEAR_DAYS away, so it has no Pair unless approved."""

    pet: Scan
    closest_mri: Scan

    @property
    def gap_days(self) -> int:
        return _gap_days(self.pet, self.closest_mri)


@dataclass(frozen=True)
class NoMri:
    """A PET whose Subject has no valid MRI."""

    pet: Scan


@dataclass(frozen=True)
class Tie:
    """A PET with two MRIs equally close to it: a data error, never resolved by picking one."""

    pet: Scan
    mris: Tuple[Scan, Scan]

    @property
    def gap_days(self) -> int:
        return _gap_days(self.pet, self.mris[0])

    @property
    def problem(self) -> Problem:
        names = " and ".join(m.path.name for m in self.mris)
        return Problem(self.pet.path, f"{names} are both {self.gap_days} days from the PET")


@dataclass(frozen=True)
class ExistingPairFolder:
    """A Pair folder on disk, and what its name says."""

    path: Path
    name: PairFolderName

    @property
    def pet_date(self) -> date:
        return self.name.pet_date

    @property
    def mri_date(self) -> date:
        return self.name.mri_date

    @property
    def gap_days(self) -> int:
        return self.name.gap_days


PairingResult = Union[Pair, OverOneYear, NoMri, Tie]


def _pair(sessions: List[Session]) -> List[PairingResult]:
    mris = [s.mri for s in sessions if s.mri]
    results: List[PairingResult] = []
    for pet in (s.pet for s in sessions if s.pet):
        if not mris:
            results.append(NoMri(pet))
            continue
        # one MRI per Session date, so at most two (one each side) can be closest
        closest = sorted(mris, key=lambda m: _gap_days(pet, m))[:2]
        if len(closest) == 2 and _gap_days(pet, closest[0]) == _gap_days(pet, closest[1]):
            results.append(Tie(pet, (closest[0], closest[1])))
        elif _gap_days(pet, closest[0]) > ONE_YEAR_DAYS:
            results.append(OverOneYear(pet, closest[0]))
        else:
            results.append(Pair(pet, closest[0]))
    return results


def _gap_days(pet: Scan, mri: Scan) -> int:
    return abs((mri.name.date - pet.name.date).days)


def _recon_folder(mri: Scan) -> Path:
    return mri.session_folder / RECON_DIRNAME / mri.name.stem


def _read_session(path: Path) -> Union[Session, Problem]:
    """The Session at ``path``, or a Problem giving every rule it breaks."""
    reasons: List[str] = []
    try:
        session_date = datetime.strptime(path.name, DATE_FORMAT).date()
    except ValueError:
        return Problem(path, f"folder name {path.name} is not a valid date")

    def scans(folder: str) -> List[Scan]:
        found = []
        if not (path / folder).is_dir():
            return found
        # endswith, not glob: glob ignores case on Windows only
        files = sorted(p for p in (path / folder).iterdir() if p.name.endswith(NII) and p.is_file())
        for file in files:
            try:
                name = parse_scan_name(file.name)
            except NameParseError as error:
                reasons.append(f"{folder}/{error}")
                continue
            if name.date != session_date:
                reasons.append(f"{folder}/{file.name} is dated {name.date:{DATE_FORMAT}}, not {path.name}")
            found.append(Scan(file, name))
        return found

    anat = scans("anat")
    mris: List[Scan] = []
    for mri_type in MRI_TYPES:
        mris = [s for s in anat if s.name.scan_type == mri_type]
        if mris:
            break
    pets = [s for s in scans("pet") if s.name.scan_type.startswith("PET")]
    for kind, candidates in (("MRIs", mris), ("PETs", pets)):
        if len(candidates) > 1:
            reasons.append(f"{len(candidates)} {kind}: " + ", ".join(s.path.name for s in candidates))

    if reasons:
        return Problem(path, "; ".join(reasons))
    return Session(path, session_date, mris[0] if mris else None, pets[0] if pets else None)
