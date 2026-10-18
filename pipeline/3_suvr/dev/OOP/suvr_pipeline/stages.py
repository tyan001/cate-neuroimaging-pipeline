"""Pipeline stages. Each stage turns subjects into independent tasks and processes one task.

Every task is idempotent: re-running a stage skips work whose output already exists (except
`quantify`, which is cheap and always recomputes), so an interrupted run can simply be restarted.
"""
from __future__ import annotations

import enum
import logging
import shutil
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Iterator, List, Optional

from .layout import LOGS_DIRNAME, PairFolder, PetMriPair, Subject
from .quantify import DEFAULT_LUT, ResultWriter, RoiTable, SuvrCalculator, VolumeTables
from .tools import Flirt, FreeSurfer, partial_path
from .tracer import TracerPolicy


class Status(enum.Enum):
    DONE = "done"
    SKIPPED = "skipped"   # output already present
    FAILED = "failed"


@dataclass
class Outcome:
    stage: str
    label: str
    status: Status
    message: str = ""


class StageError(RuntimeError):
    """A task cannot complete; the message is reported in the summary."""


@contextmanager
def task_log(name: str, log_file: Path) -> Iterator[logging.Logger]:
    """A logger that writes to ``log_file`` for the duration of one task.

    Console output is handled by the root logger configured in the CLI; this only adds the
    per-task file inside the data tree (alongside the outputs it describes). The handler sits on
    the package logger so warnings from any suvr_pipeline module during the task land in it too.
    Workers run one task at a time, so handlers never overlap within a process.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    package = logging.getLogger("suvr_pipeline")
    handler = logging.FileHandler(log_file)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    package.addHandler(handler)
    try:
        yield package.getChild(f"task.{name}")
    finally:
        package.removeHandler(handler)
        handler.close()


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class Stage(ABC):
    name: ClassVar[str]

    @abstractmethod
    def tasks(self, subject: Subject) -> List[Any]:
        """Units of work for one subject; each must be picklable and have a ``label``."""

    @abstractmethod
    def log_file(self, task: Any) -> Path: ...

    @abstractmethod
    def process(self, task: Any, log: logging.Logger) -> Status:
        """Do the work; return DONE or SKIPPED, or raise to fail."""

    def run(self, task: Any) -> Outcome:
        """Entry point executed in worker processes. Never raises."""
        try:
            with task_log(self.name, self.log_file(task)) as log:
                log.info("[%s] %s", self.name, task.label)
                try:
                    status = self.process(task, log)
                except Exception as e:
                    log.exception("FAILED: %s", e)
                    raise
                log.info("[%s] %s: %s", self.name, task.label, status.value)
                return Outcome(self.name, task.label, status)
        except Exception as e:
            return Outcome(self.name, task.label, Status.FAILED, f"{type(e).__name__}: {e}")


@dataclass
class PrepareStage(Stage):
    """Build each PET x closest-MRI pair folder: RAS NIfTI T1 + aparc+aseg, volume CSVs, PET copy."""

    name: ClassVar[str] = "prepare"
    freesurfer: FreeSurfer = field(default_factory=FreeSurfer)

    STATS = (
        ("aparcstatsVolumLeft", ["aparcstats2table", "--hemi", "lh", "--meas", "volume"]),
        ("aparcstatsVolumRight", ["aparcstats2table", "--hemi", "rh", "--meas", "volume"]),
        ("asegVolume", ["asegstats2table", "-m", "volume"]),
    )

    def tasks(self, subject: Subject) -> List[PetMriPair]:
        return list(subject.pairs())

    def log_file(self, pair: PetMriPair) -> Path:
        return pair.suvr_dir / LOGS_DIRNAME / f"suvr_setup_{pair.pet.date}_{_timestamp()}.log"

    def process(self, pair: PetMriPair, log: logging.Logger) -> Status:
        folder = pair.folder
        fs_subject = pair.freesurfer_subject_dir
        fs_mri, fs_stats = fs_subject / "mri", fs_subject / "stats"
        if not fs_mri.is_dir():
            raise StageError(f"FreeSurfer mri directory not found: {fs_mri} (has recon-all run?)")

        did_work = False
        for d in (folder.mri_dir, folder.res_dir, folder.register_dir):
            d.mkdir(parents=True, exist_ok=True)

        # Same RAS orientation for both, so aparc+aseg voxels index the registered PET directly.
        prefix = pair.mri.stem
        for src, dst_name in (("T1.mgz", pair.mri.name), ("aparc+aseg.mgz", f"{prefix}_aparc+aseg.nii")):
            dst = folder.mri_dir / dst_name
            if not dst.exists():
                self.freesurfer.convert(fs_mri / src, dst, log)
                did_work = True

        for suffix, command in self.STATS:
            dst = folder.mri_dir / f"{prefix}_{suffix}.csv"
            if dst.exists():
                continue
            precomputed = fs_stats / f"{suffix}.csv"
            if precomputed.exists():
                dst.write_text(precomputed.read_text().replace("\t", ","))
            else:
                cmd = [command[0], "--subjects", fs_subject.name] + command[1:]
                self.freesurfer.stats_table(cmd, fs_subject.parent, dst, log)
            log.info("- Wrote %s", dst.name)
            did_work = True

        pet_copy = folder.mri_dir / pair.pet.name
        if not pet_copy.exists():
            tmp = partial_path(pet_copy)
            shutil.copy2(pair.pet.path, tmp)
            tmp.replace(pet_copy)
            log.info("- Copied %s", pair.pet.name)
            did_work = True

        return Status.DONE if did_work else Status.SKIPPED


@dataclass
class RegisterStage(Stage):
    """FLIRT the PET copy in each pair folder into that folder's T1 space."""

    name: ClassVar[str] = "register"
    flirt: Flirt = field(default_factory=Flirt)

    def tasks(self, subject: Subject) -> List[PairFolder]:
        return subject.pair_folders()

    def log_file(self, folder: PairFolder) -> Path:
        return folder.pet_output_dir / LOGS_DIRNAME / f"pet_registration_{_timestamp()}.log"

    @staticmethod
    def output_name(pet, mri) -> str:
        moving = pet.with_extra(f"{pet.subject_id}-{pet.date}")
        ref = mri.with_extra(f"{mri.subject_id}-{mri.date}_{mri.modality}")
        return f"{moving}_reg_{ref}.nii"

    def process(self, folder: PairFolder, log: logging.Logger) -> Status:
        t1s, pets = folder.t1_images(), folder.source_pets()
        if not t1s or not pets:
            raise StageError(f"{folder.mri_dir} needs a T1 and a PET image (run `prepare` first)")

        did_work = False
        for mri in t1s:
            for pet in pets:
                out = folder.register_dir / self.output_name(pet, mri)
                if out.exists():
                    log.info("- Exists, skipping: %s", out.name)
                    continue
                self.flirt.register(pet.path, mri.path, out, log)
                log.info("- Wrote %s", out.name)
                did_work = True
        return Status.DONE if did_work else Status.SKIPPED


@dataclass
class QuantifyStage(Stage):
    """Regional SUVR and Centiloid from the registered PET and aparc+aseg."""

    name: ClassVar[str] = "quantify"
    tracers: TracerPolicy = field(default_factory=TracerPolicy)
    lut_path: Path = DEFAULT_LUT
    _rois: Optional[RoiTable] = field(default=None, init=False, repr=False)

    @property
    def rois(self) -> RoiTable:
        if self._rois is None:
            self._rois = RoiTable.load(self.lut_path)
        return self._rois

    def __getstate__(self):
        # Workers load the LUT themselves rather than receiving a pickled DataFrame per task.
        return {**self.__dict__, "_rois": None}

    def tasks(self, subject: Subject) -> List[PairFolder]:
        return subject.pair_folders()

    def log_file(self, folder: PairFolder) -> Path:
        return folder.subject_dir / LOGS_DIRNAME / f"pet_suvr_processing_{folder.name}_{_timestamp()}.log"

    def process(self, folder: PairFolder, log: logging.Logger) -> Status:
        pets = folder.registered_pets()
        if not pets:
            raise StageError(f"No registered PET in {folder.register_dir} (run `register` first)")
        if len(pets) > 1:
            log.warning("Multiple registered PETs in %s; using %s", folder.register_dir, pets[0].name)
        pet = pets[0]

        aparc = folder.aparc_aseg()
        if aparc is None:
            raise StageError(f"No *_aparc+aseg.nii in {folder.mri_dir}")

        scan_date = folder.scan_date()
        if scan_date is None:
            raise StageError("Cannot determine PET scan date (needed to pick the tracer)")
        tracer = self.tracers.for_date(scan_date)

        log.info("- PET: %s", pet)
        log.info("- aparc+aseg: %s", aparc)
        log.info("- Scan date %s -> %s", scan_date, tracer.name)

        volumes = VolumeTables.load(folder.mri_dir, aparc.stem.replace("_aparc+aseg", ""))
        result = SuvrCalculator(self.rois).compute_files(pet, aparc, volumes)
        ResultWriter(self.rois).write(result, folder.res_dir, folder.name, pet.name, tracer)
        if not result.suv_cer > 0:
            # Files are still written (as suvr.py did), but every SUVR is 0 and the Centiloid is
            # just -intercept. Seen with -32768 fill values from a bad PET or failed registration.
            raise StageError(
                f"Cerebellum reference SUV is {result.suv_cer} (<= 0); SUVR/Centiloid in "
                f"{folder.res_dir} are invalid -- check the PET and its registration"
            )
        log.info("- Global SUVR %.4f, Centiloid %.1f",
                 result.regional["Global"], tracer.centiloid(result.regional["Global"]))
        return Status.DONE

