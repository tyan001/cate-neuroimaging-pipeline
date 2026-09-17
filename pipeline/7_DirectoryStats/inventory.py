"""Find MRI and PET scans in an ADRC tree that were never (fully) processed.

Read-only. Every scan under ``<root>/<subject>/<session>/{anat,pet}/`` gets one status:

MRI (``anat/*.nii``)
    no_freesurfer      no ``freesurfer741/<scan stem>/`` folder      -> recon-all + segmentHA_T1.sh
    no_hippocampus     recon complete, no hippocampal subfield stats -> segmentHA_T1.sh
    recon_failed       ``scripts/recon-all.error`` present           -> report only
    recon_incomplete   folder exists but outputs are missing         -> report only
    wrong_session      filename date is not the session folder's date -> report only
    complete

PET (``pet/*_PET*.nii``), paired with its closest-dated T1w/CorMPRAGE MRI, as ``prepare`` does
    waiting_for_mri          the subject has no MRI yet                      -> report only
    waiting_for_freesurfer   the closest MRI has no finished recon-all yet   -> after the MRI step
    no_suvr                  no pair folder for (PET, closest MRI)           -> prepare/register/quantify
    incomplete_suvr          pair folder exists but has no SUVR result       -> prepare/register/quantify
    bad_name                 filename does not parse as <subj>-<YYYYMMDD>_PET[...].nii
    wrong_session            filename date is not the session folder's date
    complete

``recon_failed`` and ``recon_incomplete`` are never processed automatically: ``recon-all -i``
refuses to start over an existing subject folder, so those need to be looked at and deleted by hand.
``wrong_session`` catches scans copied into another session's folder (the ingest step can do this
for subjects with several sessions); processing them would duplicate another session's work.
"""
from __future__ import annotations

import enum
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Repo layout first (pipeline/7_DirectoryStats, pipeline/2_freesurfer/dev, ...), then the Docker
# image layout (/workspace/directory_stats, /workspace/dev, /workspace/suvr/dev/OOP).
FREESURFER_CODE_DIRS = (HERE.parent / "2_freesurfer" / "dev", HERE.parent / "dev")
SUVR_CODE_DIRS = (HERE.parent / "3_suvr" / "dev" / "OOP", HERE.parent / "suvr" / "dev" / "OOP")
LUT_CANDIDATES = (HERE.parent / "3_suvr" / "FreesurferLUTR.txt", HERE.parent / "suvr" / "FreesurferLUTR.txt")


def add_code_dir(candidates) -> Path:
    for d in candidates:
        if d.is_dir():
            if str(d) not in sys.path:
                sys.path.insert(0, str(d))
            return d
    raise ImportError(f"Pipeline code not found; looked in: {', '.join(map(str, candidates))}")


add_code_dir(SUVR_CODE_DIRS)

from suvr_pipeline.layout import (  # noqa: E402
    FREESURFER_DIRNAME,
    LOGS_DIRNAME,
    PetMriPair,
    closest_mri,
)
from suvr_pipeline.naming import ScanFile  # noqa: E402

# Top-level folders under the root that are not subjects.
NON_SUBJECT_DIRS = {LOGS_DIRNAME, "fs_logs"}
# Outputs a finished recon-all leaves behind; `prepare` needs all of them.
RECON_OUTPUTS = (
    "mri/T1.mgz",
    "mri/aparc+aseg.mgz",
    "stats/aseg.stats",
    "stats/lh.aparc.stats",
    "stats/rh.aparc.stats",
)
HIPPO_OUTPUTS = ("stats/hipposubfields.lh.T1.v22.stats", "stats/hipposubfields.rh.T1.v22.stats")
SUVR_RESULT_SUFFIX = "_suvr_combined_cerebellum.csv"


class MriState(enum.StrEnum):
    NO_FREESURFER = "no_freesurfer"
    NO_HIPPOCAMPUS = "no_hippocampus"
    RECON_FAILED = "recon_failed"
    RECON_INCOMPLETE = "recon_incomplete"
    WRONG_SESSION = "wrong_session"
    COMPLETE = "complete"


class PetState(enum.StrEnum):
    WAITING_FOR_MRI = "waiting_for_mri"
    WAITING_FOR_FREESURFER = "waiting_for_freesurfer"
    NO_SUVR = "no_suvr"
    INCOMPLETE_SUVR = "incomplete_suvr"
    BAD_NAME = "bad_name"
    WRONG_SESSION = "wrong_session"
    COMPLETE = "complete"


MRI_TODO = (MriState.NO_FREESURFER, MriState.NO_HIPPOCAMPUS)
PET_TODO = (PetState.NO_SUVR, PetState.INCOMPLETE_SUVR)


@dataclass(frozen=True)
class MriRecord:
    subject: str
    session: str
    scan: Path
    state: MriState
    detail: str = ""

    @property
    def fs_path(self) -> Path:
        """SUBJECTS_DIR for this scan: ``<session>/freesurfer741``."""
        return self.scan.parent.parent / FREESURFER_DIRNAME

    @property
    def fs_subject_dir(self) -> Path:
        return self.fs_path / self.scan.stem


@dataclass(frozen=True)
class PetRecord:
    subject: str
    session: str
    scan: Path
    state: PetState
    detail: str = ""
    mri: Path | None = None
    pair: PetMriPair | None = None


# ---- tree walking ------------------------------------------------------


def subject_dirs(root: Path, only=None) -> list[Path]:
    if only:
        dirs = [root / s for s in only]
        missing = [str(d) for d in dirs if not d.is_dir()]
        if missing:
            raise FileNotFoundError(f"Subject directory not found: {', '.join(missing)}")
        return dirs
    return sorted(
        d for d in root.iterdir()
        if d.is_dir() and d.name not in NON_SUBJECT_DIRS and not d.name.startswith(".")
    )


def _session_files(subject: Path, modality: str, pattern: str) -> list[Path]:
    # Fixed depth on purpose: rglob would descend into every freesurfer741/ and suvr/ tree.
    return sorted(p for p in subject.glob(f"*/{modality}/{pattern}") if p.is_file())


def mri_files(subject: Path) -> list[Path]:
    """Every ``anat/*.nii`` -- what the FreeSurfer stage runs recon-all on."""
    return _session_files(subject, "anat", "*.nii")


def session_mismatch(path: Path) -> str:
    """Why ``path``'s filename date disagrees with its session folder, or "" if it doesn't."""
    scan = ScanFile.try_parse(path)
    session = path.parent.parent.name
    if scan is None or scan.date == session:
        return ""
    return f"filename date {scan.date} is not session {session}"


def pairing_mris(subject: Path) -> list[ScanFile]:
    """The T1w/CorMPRAGE scans ``prepare`` can pair a PET with (same patterns as layout.MRI_PATTERNS)."""
    scans = []
    for p in mri_files(subject):
        if ("T1w" in p.name or "CorMPRAGE" in p.name) and not session_mismatch(p):
            scan = ScanFile.try_parse(p)
            if scan is not None:
                scans.append(scan)
    return scans


def pet_files(subject: Path) -> list[Path]:
    return [p for p in _session_files(subject, "pet", "*.nii") if "_PET" in p.name]


# ---- status ------------------------------------------------------------


def _missing(base: Path, rel_paths) -> list[str]:
    return [rel for rel in rel_paths if not (base / rel).exists()]


def mri_state(fs_subject_dir: Path) -> tuple[MriState, str]:
    if not fs_subject_dir.is_dir():
        return MriState.NO_FREESURFER, ""
    scripts = fs_subject_dir / "scripts"
    if (scripts / "recon-all.error").exists():
        return MriState.RECON_FAILED, "scripts/recon-all.error present"
    missing = _missing(fs_subject_dir, RECON_OUTPUTS)
    if missing:
        running = any(scripts.glob("IsRunning*"))
        why = "IsRunning file present (still running, or killed); " if running else ""
        return MriState.RECON_INCOMPLETE, f"{why}missing {', '.join(missing)}"
    missing = _missing(fs_subject_dir, HIPPO_OUTPUTS)
    if missing:
        return MriState.NO_HIPPOCAMPUS, f"missing {', '.join(missing)}"
    return MriState.COMPLETE, ""


def recon_ready(fs_subject_dir: Path) -> bool:
    """recon-all finished well enough for ``prepare`` (hippocampal step not required)."""
    return (
        fs_subject_dir.is_dir()
        and not (fs_subject_dir / "scripts" / "recon-all.error").exists()
        and not _missing(fs_subject_dir, RECON_OUTPUTS)
    )


def suvr_done(pair: PetMriPair) -> bool:
    folder = pair.folder
    return (folder.res_dir / f"{folder.name}{SUVR_RESULT_SUFFIX}").is_file()


def other_pairings(pair: PetMriPair) -> list[str]:
    """Pair folders under this PET's output folder that use a different MRI."""
    out = pair.pet_output_dir
    if not out.is_dir():
        return []
    return sorted(
        d.name for d in out.iterdir()
        if d.is_dir() and "_mri_" in d.name and d.name != pair.pair_dir_name
    )


def inventory_mri(subject: Path) -> list[MriRecord]:
    records = []
    for scan in mri_files(subject):
        mismatch = session_mismatch(scan)
        if mismatch:
            state, detail = MriState.WRONG_SESSION, mismatch
        else:
            state, detail = mri_state(scan.parent.parent / FREESURFER_DIRNAME / scan.stem)
        records.append(MriRecord(subject.name, scan.parent.parent.name, scan, state, detail))
    return records


def _valid_date(scan: ScanFile) -> bool:
    try:
        return scan.acquired is not None
    except ValueError:
        return False


def inventory_pet(subject: Path) -> list[PetRecord]:
    mris = pairing_mris(subject)
    records = []
    for path in pet_files(subject):
        session = path.parent.parent.name
        pet = ScanFile.try_parse(path)
        if pet is None or not _valid_date(pet):
            records.append(PetRecord(subject.name, session, path, PetState.BAD_NAME,
                                     "expected <subj>-<YYYYMMDD>_PET[_extra].nii"))
            continue
        mismatch = session_mismatch(path)
        if mismatch:
            records.append(PetRecord(subject.name, session, path, PetState.WRONG_SESSION, mismatch))
            continue

        mri = closest_mri(pet, mris)
        if mri is None:
            records.append(PetRecord(subject.name, session, path, PetState.WAITING_FOR_MRI,
                                     "subject has no T1w/CorMPRAGE MRI"))
            continue

        pair = PetMriPair(pet, mri)
        gap = f"closest MRI {mri.date} ({abs((mri.acquired - pet.acquired).days)} days)"
        if not recon_ready(pair.freesurfer_subject_dir):
            state, _ = mri_state(pair.freesurfer_subject_dir)
            records.append(PetRecord(subject.name, session, path, PetState.WAITING_FOR_FREESURFER,
                                     f"{gap}: {state.value}", mri.path, pair))
            continue

        others = other_pairings(pair)
        notes = [gap] + ([f"also paired with {', '.join(others)}"] if others else [])
        if suvr_done(pair):
            state = PetState.COMPLETE
        elif pair.folder.path.is_dir():
            state = PetState.INCOMPLETE_SUVR
        else:
            state = PetState.NO_SUVR
        records.append(PetRecord(subject.name, session, path, state, "; ".join(notes), mri.path, pair))
    return records


def inventory(root: Path, subjects=None) -> tuple[list[MriRecord], list[PetRecord]]:
    mri, pet = [], []
    for subject in subject_dirs(root, subjects):
        mri.extend(inventory_mri(subject))
        pet.extend(inventory_pet(subject))
    return mri, pet


def find_lut() -> Path:
    for p in LUT_CANDIDATES:
        if p.is_file():
            return p
    raise FileNotFoundError(f"FreesurferLUTR.txt not found; looked in: {', '.join(map(str, LUT_CANDIDATES))}")
