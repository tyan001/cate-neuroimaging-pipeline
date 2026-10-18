#!/usr/bin/env python3
"""Process only the MRI and PET scans that find_missing.py reports as not done.

    python3 process_missing.py all  /path/to/ADRC --dry-run           # show the plan
    nohup python3 process_missing.py all /path/to/ADRC --cores 8 > missing.log 2>&1 &

    python3 process_missing.py mri  /path/to/ADRC --cores 8           # recon-all + segmentHA_T1.sh
    python3 process_missing.py suvr /path/to/ADRC --cores 8           # prepare + register + quantify

Run it inside the fs7-fsl container. It needs recon-all, segmentHA_T1.sh, mri_convert and flirt.

mri   no_freesurfer   -> recon-all -all, then segmentHA_T1.sh if recon-all succeeds
      no_hippocampus  -> segmentHA_T1.sh only
suvr  no_suvr / incomplete_suvr -> the three SUVR stages, on those PET x closest-MRI pairs only
all   mri, then suvr. The PET inventory is taken again after the MRI step, so a PET that was
      waiting for its MRI's recon-all is processed in the same run.

Failed or half-finished recons (recon_failed, recon_incomplete) and PETs with no MRI are only
reported. The FreeSurfer and SUVR code is reused from 2_freesurfer/dev and 3_suvr/dev/OOP.
"""
from __future__ import annotations

import argparse
import logging
import multiprocessing as mp
import os
import shutil
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from inventory import (
    FREESURFER_CODE_DIRS,
    MRI_TODO,
    PET_TODO,
    MriState,
    PetState,
    add_code_dir,
    find_lut,
    inventory,
)

add_code_dir(FREESURFER_CODE_DIRS)

from freesurfer_pipeline import process_subject_freesurfer  # noqa: E402
from hippocampus_pipeline import process_subject_hippocampus  # noqa: E402
from suvr_pipeline.layout import Subject  # noqa: E402
from suvr_pipeline.runner import StageRunner  # noqa: E402
from suvr_pipeline.stages import PrepareStage, QuantifyStage, RegisterStage, Stage, Status  # noqa: E402
from suvr_pipeline.tracer import TRACERS, TracerPolicy  # noqa: E402

log = logging.getLogger("process_missing")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
MRI_TOOLS = ("recon-all", "segmentHA_T1.sh")
SUVR_TOOLS = ("mri_convert", "aparcstats2table", "asegstats2table")


def setup_logging(log_file: Path | None) -> None:
    handlers = [logging.StreamHandler()]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S",
                        handlers=handlers, force=True)


def _worker_init(log_file):
    # Forked workers inherit the parent's handlers; spawned ones start with none.
    if not logging.getLogger().handlers:
        setup_logging(log_file)


def missing_tools(names) -> list[str]:
    return [n for n in names if shutil.which(n) is None]


# ---- MRI -----------------------------------------------------------------


def process_mri(record, run_hippocampus=True) -> dict:
    """recon-all (if there is no recon yet) then segmentHA_T1.sh, for one anat scan."""
    subject = record.scan.stem
    result = {"scan": subject, "state": record.state, "fs_success": None, "hc_success": None, "time": 0.0}
    start = time.time()
    fs_path = record.fs_path
    if record.state is MriState.NO_FREESURFER:
        fs = process_subject_freesurfer(record.scan, log)
        result["fs_success"] = fs["fs_success"]
        fs_path = fs["fs_path"]
        if not fs["fs_success"]:
            log.error("Skipping hippocampus segmentation for %s due to FreeSurfer failure", subject)
    if run_hippocampus and result["fs_success"] is not False:
        result["hc_success"] = process_subject_hippocampus(subject, fs_path, log)["hc_success"]
    result["time"] = time.time() - start
    return result


def run_mri(records, cores, run_hippocampus, log_file) -> int:
    todo = [r for r in records if r.state is MriState.NO_FREESURFER
            or (run_hippocampus and r.state is MriState.NO_HIPPOCAMPUS)]
    workers = min(cores, len(todo))
    log.info("=== MRI: %d scan(s) to process with %d worker(s) ===", len(todo), workers)
    if not todo:
        return 0

    if workers == 1:
        results = [process_mri(r, run_hippocampus) for r in todo]
    else:
        with mp.Pool(workers, initializer=_worker_init, initargs=(log_file,)) as pool:
            results = pool.starmap(process_mri, [(r, run_hippocampus) for r in todo])

    fs_failed = [r["scan"] for r in results if r["fs_success"] is False]
    hc_failed = [r["scan"] for r in results if r["hc_success"] is False]
    n_recon = sum(r["fs_success"] is not None for r in results)
    n_hippo = sum(r["hc_success"] is not None for r in results)
    log.info("=== MRI SUMMARY ===")
    log.info("recon-all succeeded: %d/%d", n_recon - len(fs_failed), n_recon)
    if fs_failed:
        log.info("recon-all failed: %s", ", ".join(fs_failed))
    if run_hippocampus:
        log.info("segmentHA_T1.sh succeeded: %d/%d", n_hippo - len(hc_failed), n_hippo)
        if hc_failed:
            log.info("segmentHA_T1.sh failed: %s", ", ".join(hc_failed))
    log.info("Total MRI time: %.2f hours", sum(r["time"] for r in results) / 3600)
    return len(fs_failed) + len(hc_failed)


# ---- SUVR ----------------------------------------------------------------


class SelectedTasks(Stage):
    """Runs ``inner`` on a fixed list of tasks instead of everything it finds for a subject."""

    def __init__(self, inner: Stage, tasks):
        self.inner = inner
        self.name = inner.name
        self._by_subject = defaultdict(list)
        for subject_id, task in tasks:
            self._by_subject[subject_id].append(task)

    def subjects(self, root: Path) -> list[Subject]:
        return [Subject(root / s) for s in sorted(self._by_subject)]

    def tasks(self, subject):
        return list(self._by_subject.get(subject.id, []))

    def log_file(self, task):
        return self.inner.log_file(task)

    def process(self, task, log):
        return self.inner.process(task, log)

    def __getstate__(self):
        # Workers only call run(); don't ship the whole task list with every task.
        return {**self.__dict__, "_by_subject": {}}


def run_selected(runner, root, stage, tasks):
    selected = SelectedTasks(stage, tasks)
    outcomes = runner.run(selected, selected.subjects(root))
    ok = {o.label for o in outcomes if o.status is not Status.FAILED}
    return ok, sum(o.status is Status.FAILED for o in outcomes)


def run_suvr(root, records, cores, compound, lut) -> int:
    todo = [r for r in records if r.state in PET_TODO]
    log.info("=== SUVR: %d PET scan(s) to process ===", len(todo))
    if not todo:
        return 0

    runner = StageRunner(cores=cores)
    pairs = [(r.subject, r.pair) for r in todo]
    ok, failed = run_selected(runner, root, PrepareStage(), pairs)

    folders = [(s, p.folder) for s, p in pairs if p.label in ok]
    ok, n = run_selected(runner, root, RegisterStage(), folders)
    failed += n

    folders = [(s, f) for s, f in folders if f.label in ok]
    _, n = run_selected(runner, root, QuantifyStage(TracerPolicy.from_name(compound), lut), folders)
    failed += n

    log.info("=== SUVR SUMMARY: %d PET scan(s), %d failed task(s) ===", len(todo), failed)
    return failed


# ---- plan / CLI -----------------------------------------------------------


def print_plan(stage, mri, pet, run_hippocampus):
    if stage in ("mri", "all"):
        todo = [r for r in mri if r.state is MriState.NO_FREESURFER
                or (run_hippocampus and r.state is MriState.NO_HIPPOCAMPUS)]
        print(f"\nMRI: {len(todo)} scan(s)")
        for r in todo:
            what = "hippocampus" if r.state is MriState.NO_HIPPOCAMPUS else (
                "recon-all + hippocampus" if run_hippocampus else "recon-all")
            print(f"  {r.subject}/{r.session}/anat/{r.scan.name}   {what}")
    if stage in ("suvr", "all"):
        todo = [r for r in pet if r.state in PET_TODO]
        print(f"\nPET: {len(todo)} scan(s)")
        for r in todo:
            print(f"  {r.subject}/{r.session}/pet/{r.scan.name}   with {r.mri.name}   {r.state.value}")
        queued = {r.scan for r in mri if r.state is MriState.NO_FREESURFER} if stage == "all" else set()
        waiting = [r for r in pet if r.state is PetState.WAITING_FOR_FREESURFER]
        later = [r for r in waiting if r.mri in queued]
        if later:
            print(f"\nPET after the MRI step: {len(later)} scan(s)")
            for r in later:
                print(f"  {r.subject}/{r.session}/pet/{r.scan.name}   with {r.mri.name}")
        skipped = [r for r in pet if r.state not in PET_TODO and r.state is not PetState.COMPLETE
                   and r not in later]
        if skipped:
            print(f"\nPET not processed: {len(skipped)} scan(s)")
            for r in skipped:
                print(f"  {r.subject}/{r.session}/pet/{r.scan.name}   {r.state.value}   {r.detail}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["mri", "suvr", "all"])
    parser.add_argument("root", type=Path, help="ADRC directory (one folder per subject)")
    parser.add_argument("--subject", action="append", metavar="ID", help="Only this subject (repeatable)")
    parser.add_argument("--cores", type=int, default=int(os.getenv("CPU_CORES", 1)),
                        help="Parallel workers (default: $CPU_CORES or 1)")
    parser.add_argument("--no-hippocampus", action="store_true", help="mri: skip segmentHA_T1.sh")
    parser.add_argument("--compound", choices=sorted(TRACERS),
                        help="suvr: force this tracer instead of inferring it from the scan date")
    parser.add_argument("--lut", type=Path, help="suvr: ROI lookup table (default: 3_suvr/FreesurferLUTR.txt)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would run and exit")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not args.root.is_dir():
        print(f"Not a directory: {args.root}", file=sys.stderr)
        return 1
    root = args.root.resolve()
    run_hippocampus = not args.no_hippocampus

    try:
        mri, pet = inventory(root, args.subject)
        lut = args.lut or (find_lut() if args.stage != "mri" else None)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    if args.dry_run:
        print_plan(args.stage, mri, pet, run_hippocampus)
        return 0

    needed = []
    if args.stage in ("mri", "all"):
        needed += MRI_TOOLS if run_hippocampus else MRI_TOOLS[:1]
    if args.stage in ("suvr", "all"):
        needed += SUVR_TOOLS
    missing = missing_tools(needed)
    if missing:
        print(f"Not found on PATH: {', '.join(missing)}. Run this inside the fs7-fsl container.",
              file=sys.stderr)
        return 1

    log_file = root / "logs" / "missing_logs" / f"process_missing_{datetime.now():%Y%m%d_%H%M%S}.log"
    setup_logging(log_file)
    log.info("process_missing %s on %s (log: %s)", args.stage, root, log_file)
    start = datetime.now()

    failed = 0
    if args.stage in ("mri", "all"):
        failed += run_mri([r for r in mri if r.state in MRI_TODO], max(1, args.cores),
                          run_hippocampus, log_file)
    if args.stage in ("suvr", "all"):
        if args.stage == "all":
            _, pet = inventory(root, args.subject)  # recon-all may have unblocked some PETs
        failed += run_suvr(root, pet, max(1, args.cores), args.compound, lut)

    for r in pet:
        if r.state in (PetState.WAITING_FOR_MRI, PetState.WAITING_FOR_FREESURFER):
            log.info("Not processed (%s): %s   %s", r.state.value, r.scan.name, r.detail)
    log.info("Finished in %s; %d failure(s)", datetime.now() - start, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
