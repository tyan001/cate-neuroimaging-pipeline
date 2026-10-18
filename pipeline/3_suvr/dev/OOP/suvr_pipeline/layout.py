"""The ADRC directory tree, modelled as objects.

    <root>/<subject>/<date>/anat/<subj>-<date>_T1w.nii                 source MRI
    <root>/<subject>/<date>/freesurfer741/<mri stem>/{mri,stats}/      recon-all output
    <root>/<subject>/<date>/pet/<subj>-<date>_PET[_x].nii              source PET
    <root>/<subject>/<date>/suvr/<subj>-<date>_PET[_x]/<pair>/         one PairFolder
        MRI/            T1 + aparc+aseg (RAS NIfTI), PET copy, 3 volume CSVs
        register_scan/  PET registered into T1 space (+ .mat)
        res/            SUVR / Centiloid outputs
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Sequence

from .naming import ScanFile

SUVR_DIRNAME = "suvr"
FREESURFER_DIRNAME = "freesurfer741"
LOGS_DIRNAME = "logs"
MRI_PATTERNS = ("*T1w*.nii", "*CorMPRAGE*.nii")
# Temporary outputs are written as <name>.partial.nii and renamed when complete.
PARTIAL_MARKER = ".partial."

log = logging.getLogger(__name__)


def _is_partial(path: Path) -> bool:
    return PARTIAL_MARKER in path.name


def _parse_all(paths: Sequence[Path]) -> List[ScanFile]:
    scans = []
    for p in paths:
        scan = ScanFile.try_parse(p)
        if scan is None:
            log.warning("Skipping file with unexpected name: %s", p)
        else:
            scans.append(scan)
    return scans


def _is_segmentation(path: Path) -> bool:
    name = path.name.lower()
    return "aparc" in name or "aseg" in name


@dataclass(frozen=True)
class Dataset:
    """Root directory containing one folder per subject."""

    root: Path

    def subjects(self, only: Optional[Sequence[str]] = None) -> List["Subject"]:
        if only:
            dirs = [self.root / s for s in only]
            missing = [d for d in dirs if not d.is_dir()]
            if missing:
                raise FileNotFoundError(f"Subject directory not found: {', '.join(map(str, missing))}")
        else:
            dirs = sorted(d for d in self.root.iterdir() if d.is_dir())
        return [Subject(d) for d in dirs]


@dataclass(frozen=True)
class Subject:
    path: Path

    @property
    def id(self) -> str:
        return self.path.name

    @property
    def logs_dir(self) -> Path:
        return self.path / LOGS_DIRNAME

    # ---- source scans -------------------------------------------------

    def pet_session_dirs(self) -> List[Path]:
        return sorted(d for d in self.path.iterdir() if d.is_dir() and (d / "pet").exists())

    def pet_scans(self) -> List[ScanFile]:
        files = []
        for session in self.pet_session_dirs():
            files.extend(f for f in sorted((session / "pet").glob("*.nii")) if "_PET" in f.name)
        return _parse_all(files)

    def mri_scans(self) -> List[ScanFile]:
        files = []
        for anat_dir in self.path.rglob("anat"):
            for pattern in MRI_PATTERNS:
                files.extend(anat_dir.glob(pattern))
        return _parse_all(sorted(files))

    def pairs(self) -> Iterator["PetMriPair"]:
        """Each PET scan paired with its closest-dated MRI (ties -> first in path order)."""
        mris = self.mri_scans()
        for pet in self.pet_scans():
            mri = closest_mri(pet, mris)
            if mri is not None:
                yield PetMriPair(pet, mri)

    # ---- existing pair folders ---------------------------------------

    def pet_output_dirs(self) -> List[Path]:
        """``<date>/suvr/<subj>-<date>_PET[...]`` folders (the level the symlink farm links)."""
        return sorted(
            d for d in self.path.glob(f"*/{SUVR_DIRNAME}/*")
            if d.is_dir() and d.name != LOGS_DIRNAME and "-" in d.name and "_PET" in d.name
        )

    def pair_folders(self) -> List["PairFolder"]:
        folders = []
        for pet_dir in self.pet_output_dirs():
            for d in sorted(pet_dir.iterdir()):
                lname = d.name.lower()
                if d.is_dir() and "_pet_" in lname and "_mri_" in lname:
                    folders.append(PairFolder(d))
        return folders


def closest_mri(pet: ScanFile, mris: Sequence[ScanFile]) -> Optional[ScanFile]:
    try:
        pet_date = pet.acquired
    except ValueError:
        log.warning("Cannot read date from PET name: %s", pet.name)
        return None
    best, best_delta = None, None
    for mri in mris:
        try:
            delta = abs((mri.acquired - pet_date).days)
        except ValueError:
            continue
        if best_delta is None or delta < best_delta:
            best, best_delta = mri, delta
    return best


@dataclass(frozen=True)
class PetMriPair:
    """A PET scan matched with an MRI; knows where its pair folder and FreeSurfer inputs live."""

    pet: ScanFile
    mri: ScanFile

    @property
    def label(self) -> str:
        return f"{self.pet.name} x {self.mri.name}"

    @property
    def suvr_dir(self) -> Path:
        return self.pet.path.parent.parent / SUVR_DIRNAME

    @property
    def pet_output_dir(self) -> Path:
        return self.suvr_dir / self.pet.with_extra(f"{self.pet.subject_id}-{self.pet.date}_PET")

    @property
    def pair_dir_name(self) -> str:
        pet_part = self.pet.with_extra(f"{self.pet.subject_id}_pet_{self.pet.date}")
        mri_part = f"mri_{self.mri.date}" + ("_CorMPRAGE" if self.mri.is_cormprage else "")
        return self.mri.with_extra(f"{pet_part}_{mri_part}")

    @property
    def folder(self) -> "PairFolder":
        return PairFolder(self.pet_output_dir / self.pair_dir_name)

    @property
    def freesurfer_subject_dir(self) -> Path:
        """``<mri session>/freesurfer741/<mri stem>`` -- the recon-all subject."""
        return self.mri.path.parent.parent / FREESURFER_DIRNAME / self.mri.stem


@dataclass(frozen=True)
class PairFolder:
    """An on-disk ``<subj>_pet_<date>_mri_<date>`` folder."""

    path: Path

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def label(self) -> str:
        return self.name

    @property
    def mri_dir(self) -> Path:
        return self.path / "MRI"

    @property
    def register_dir(self) -> Path:
        return self.path / "register_scan"

    @property
    def res_dir(self) -> Path:
        return self.path / "res"

    @property
    def pet_output_dir(self) -> Path:
        return self.path.parent

    @property
    def subject_dir(self) -> Path:
        # <subject>/<date>/suvr/<pet dir>/<pair>
        return self.path.parents[3]

    def _nii(self, directory: Path, pattern: str = "*.nii") -> List[Path]:
        if not directory.is_dir():
            return []
        return sorted(p for p in directory.glob(pattern) if not _is_partial(p))

    # MRI/ contents
    def t1_images(self) -> List[ScanFile]:
        files = {p for pat in MRI_PATTERNS for p in self._nii(self.mri_dir, pat)}
        return _parse_all([p for p in sorted(files) if not _is_segmentation(p)])

    def source_pets(self) -> List[ScanFile]:
        return _parse_all(self._nii(self.mri_dir, "*PET*.nii"))

    def aparc_aseg(self) -> Optional[Path]:
        found = self._nii(self.mri_dir, "*_aparc+aseg.nii")
        return found[0] if found else None

    # register_scan/ contents
    def registered_pets(self) -> List[Path]:
        return [p for p in self._nii(self.register_dir) if not _is_segmentation(p)]

    def scan_date(self) -> Optional[str]:
        """PET date, from the registered PET name or else from the folder name."""
        for pet in self.registered_pets():
            scan = ScanFile.try_parse(pet)
            if scan:
                return scan.date
        parts = self.name.split("_")
        if len(parts) > 2 and len(parts[2]) == 8 and parts[2].isdigit():
            return parts[2]
        return None
