#!/usr/bin/env python3
"""Merge a processed batch ADRC folder into the main ADRC folder, append-only.

    python3 merge_batch.py --source /data/Processing/Both/batch87/ADRC --dest /data/NWSI/ADRC            # plan only
    python3 merge_batch.py --source /data/Processing/Both/batch87/ADRC --dest /data/NWSI/ADRC --execute  # copy

    ADRC_ROOT=/data/NWSI/ADRC PROCESSING_ROOT=/data/Processing python3 merge_batch.py --source 87 --execute

Nothing is copied without --execute. Like the sync_*.sh scripts it never overwrites a file in the
main folder (rsync --ignore-existing --copy-links), but it checks the batch first:

  * Unfinished work stays behind. A recon-all folder that failed or is incomplete, and an SUVR
    pair folder with no result CSV, are not copied (--include-incomplete to copy them anyway).
    The scans themselves are copied, so pipeline/7_DirectoryStats/find_missing.py on the main
    folder lists them for reprocessing.
  * freesurfer741/fsaverage is never copied. recon-all links it to the FreeSurfer install, and
    following the link would put a 480 MB template copy in every session.
  * Stray scans stay behind: an anat/ or pet/ file whose filename date is not its session folder.
  * No mixing of two runs: if the main folder already has a recon-all subject folder or SUVR
    pair folder, the batch's copy of it is skipped as a whole.
  * Files already in the main folder are never replaced. Those whose content differs from the
    batch copy are listed as conflicts (a re-delivered file that differs only in its modification
    time counts as the same).
  * Batch-level logs go under the main folder's logs/: fs_logs/ADRC.log -> logs/fs_logs/<batch>.log.

After copying, every copied file is checked for existence and size in the main folder.
The run log is written to <dest>/logs/merge_logs/<batch>_<timestamp>.log.
"""
from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventory import (  # noqa: E402
    FREESURFER_DIRNAME,
    SUVR_RESULT_SUFFIX,
    MriState,
    PetState,
    inventory,
    subject_dirs,
)

RSYNC = ["rsync", "-a", "--copy-links", "--ignore-existing"]
BAD_RECON = (MriState.RECON_FAILED, MriState.RECON_INCOMPLETE)


@dataclass
class Plan:
    source: Path
    dest: Path
    batch: str
    copy: list[str] = field(default_factory=list)               # paths relative to source
    copy_bytes: int = 0
    same: int = 0                                                # already in dest, identical
    conflicts: list[str] = field(default_factory=list)          # already in dest, different
    skipped: dict[str, str] = field(default_factory=dict)       # relative path -> reason
    logs: list[tuple[Path, str]] = field(default_factory=list)  # (source file, path relative to dest)
    new_sessions: list[str] = field(default_factory=list)


def batch_name(source: Path) -> str:
    return source.parent.name if source.name == "ADRC" else source.name


def resolve_source(value: str) -> Path:
    """A path, or a batch number resolved like sync_batch.sh: $PROCESSING_ROOT/Both/batch<N>/ADRC."""
    if value.isdigit() and not Path(value).exists():
        root = Path(os.environ.get("PROCESSING_ROOT", "Processing"))
        return root / "Both" / f"batch{value}" / "ADRC"
    return Path(value)


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def excluded_units(source: Path, include_incomplete: bool) -> dict[str, str]:
    """Folders/files under source that must not be copied, with the reason."""
    out = {}
    for link in source.glob(f"*/*/{FREESURFER_DIRNAME}/fsaverage"):
        out[rel(link, source)] = "fsaverage template from the FreeSurfer install, not subject data"
    mri, pet = inventory(source)
    for r in mri:
        if r.state is MriState.WRONG_SESSION:
            out[rel(r.scan, source)] = r.detail
        elif r.state in BAD_RECON and not include_incomplete:
            out[rel(r.fs_subject_dir, source)] = f"{r.state.value}: {r.detail}"
    for r in pet:
        if r.state is PetState.WRONG_SESSION:
            out[rel(r.scan, source)] = r.detail
    if not include_incomplete:
        for pair in source.glob("*/*/suvr/*/*_mri_*"):
            if pair.is_dir() and not (pair / "res" / f"{pair.name}{SUVR_RESULT_SUFFIX}").is_file():
                out[rel(pair, source)] = "SUVR pair folder has no result (unfinished)"
    return out


def unit_dirs(source: Path) -> list[Path]:
    """Folders that are copied whole or not at all: recon-all subjects and SUVR pair folders."""
    return [d for d in (*source.glob(f"*/*/{FREESURFER_DIRNAME}/*"), *source.glob("*/*/suvr/*/*_mri_*"))
            if d.is_dir() and d.name != "fsaverage"]


def walk_files(top: Path):
    for dirpath, _, filenames in os.walk(top, followlinks=True):
        for name in filenames:
            yield Path(dirpath) / name


def is_under(path: str, prefixes) -> str | None:
    for p in prefixes:
        if path == p or path.startswith(p + "/"):
            return p
    return None


def log_destination(path: Path, top: Path, batch: str) -> str:
    """Where a file from a batch-level (non-subject) folder goes in the main folder."""
    inner = path.relative_to(top)
    if top.name == "logs":
        return f"logs/{inner.as_posix()}"
    if top.name == "fs_logs" and inner.parent == Path("."):
        name = f"{batch}{path.suffix}" if path.stem == "ADRC" else f"{batch}_{path.name}"
        return f"logs/fs_logs/{name}"
    return f"logs/{top.name}/{batch}/{inner.as_posix()}"


def build_plan(source: Path, dest: Path, include_incomplete: bool = False) -> Plan:
    plan = Plan(source, dest, batch_name(source))
    plan.skipped = excluded_units(source, include_incomplete)
    for unit in unit_dirs(source):
        r = rel(unit, source)
        if r not in plan.skipped and (dest / r).exists():
            plan.skipped[r] = "already in the main folder (not merged into it)"
    skip_prefixes = sorted(plan.skipped)

    subjects = subject_dirs(source)
    for subject in subjects:
        for session in sorted(p for p in subject.iterdir() if p.is_dir() and p.name != "logs"):
            if not (dest / rel(session, source)).exists():
                plan.new_sessions.append(rel(session, source))
        for f in sorted(walk_files(subject)):
            r = rel(f, source)
            if is_under(r, skip_prefixes):
                continue
            target = dest / r
            if target.exists():
                s, t = f.stat(), target.stat()
                if s.st_size == t.st_size and (int(s.st_mtime) == int(t.st_mtime)
                                               or filecmp.cmp(f, target, shallow=False)):
                    plan.same += 1
                else:
                    plan.conflicts.append(r)
                continue
            plan.copy.append(r)
            plan.copy_bytes += f.stat().st_size

    subject_names = {s.name for s in subjects}
    for top in sorted(source.iterdir()):
        if top.is_dir() and top.name not in subject_names:
            for f in sorted(walk_files(top)):
                target = log_destination(f, top, plan.batch)
                if not (dest / target).exists():
                    plan.logs.append((f, target))
    return plan


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


def report(plan: Plan, out) -> None:
    def p(line=""):
        print(line, file=out)

    p(f"Batch:  {plan.batch}")
    p(f"Source: {plan.source}")
    p(f"Dest:   {plan.dest}")
    p()
    p(f"New sessions:              {len(plan.new_sessions)}")
    p(f"Files to copy:             {len(plan.copy)} ({human(plan.copy_bytes)})")
    p(f"Already present, same:     {plan.same}")
    p(f"Already present, differs:  {len(plan.conflicts)}  (not copied)")
    p(f"Skipped folders/files:     {len(plan.skipped)}")
    p(f"Batch logs to copy:        {len(plan.logs)}")

    per_subject = Counter(r.split("/", 1)[0] for r in plan.copy)
    if per_subject:
        p("\nFiles to copy per subject:")
        new_by_subject = defaultdict(list)
        for s in plan.new_sessions:
            subj, date = s.split("/", 1)
            new_by_subject[subj].append(date)
        for subj in sorted(per_subject):
            new = f"   new sessions: {', '.join(new_by_subject[subj])}" if new_by_subject[subj] else ""
            p(f"  {subj}  {per_subject[subj]:>6}{new}")
    if plan.skipped:
        p("\nSkipped:")
        for r, why in sorted(plan.skipped.items()):
            p(f"  {r}   {why}")
    if plan.conflicts:
        p("\nConflicts (the main folder's copy is kept):")
        for r in plan.conflicts:
            p(f"  {r}")
    if plan.logs:
        p("\nBatch logs:")
        for f, target in plan.logs:
            p(f"  {rel(f, plan.source)} -> {target}")


def run_rsync(args: list[str], log) -> None:
    print(f"$ {' '.join(args)}", file=log, flush=True)
    result = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise RuntimeError(f"rsync exited {result.returncode} (see log)")


def execute(plan: Plan, log) -> list[str]:
    """Copy the planned files; return the ones that are missing or wrong-sized afterwards."""
    if plan.copy:
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as files_from:
            files_from.write("\n".join(plan.copy) + "\n")
            files_from.flush()
            run_rsync(RSYNC + ["--itemize-changes", f"--files-from={files_from.name}",
                               f"{plan.source}/", f"{plan.dest}/"], log)
    for f, target in plan.logs:
        (plan.dest / target).parent.mkdir(parents=True, exist_ok=True)
        run_rsync(RSYNC + [str(f), str(plan.dest / target)], log)

    bad = []
    for r in plan.copy:
        target = plan.dest / r
        if not target.is_file() or target.stat().st_size != (plan.source / r).stat().st_size:
            bad.append(r)
    return bad


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for s in self.streams:
            s.write(text)

    def flush(self):
        for s in self.streams:
            s.flush()



def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="Batch ADRC folder, or a batch number ($PROCESSING_ROOT/Both/batch<N>/ADRC)")
    parser.add_argument("--dest", type=Path, default=os.environ.get("ADRC_ROOT"),
                        help="Main ADRC folder (default: $ADRC_ROOT)")
    parser.add_argument("--execute", action="store_true", help="Copy. Without it, only the plan is printed.")
    parser.add_argument("--include-incomplete", action="store_true",
                        help="Also copy failed/unfinished recon-all and SUVR folders")
    args = parser.parse_args(argv)

    source = resolve_source(args.source).resolve()
    if args.dest is None:
        parser.error("--dest is required unless $ADRC_ROOT is set")
    dest = Path(args.dest).resolve()
    for label, path in (("Source", source), ("Destination", dest)):
        if not path.is_dir():
            print(f"{label} is not a directory: {path}", file=sys.stderr)
            return 1
    if source == dest or dest in source.parents or source in dest.parents:
        print("Source and destination must be separate folders", file=sys.stderr)
        return 1
    if args.execute and shutil.which("rsync") is None:
        print("rsync not found on PATH", file=sys.stderr)
        return 1

    plan = build_plan(source, dest, args.include_incomplete)
    if not args.execute:
        report(plan, sys.stdout)
        print("\nDry run: nothing copied. Add --execute to copy.")
        return 0

    log_path = dest / "logs" / "merge_logs" / f"{plan.batch}_{datetime.now():%Y%m%d_%H%M%S}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        out = Tee(sys.stdout, log)
        report(plan, out)
        print(f"\nCopying... (rsync output: {log_path})", file=out, flush=True)
        try:
            bad = execute(plan, log)
        except RuntimeError as e:
            print(f"FAILED: {e}", file=out)
            return 1
        if bad:
            print(f"\nVERIFY FAILED: {len(bad)} file(s) missing or wrong size in the main folder:", file=out)
            for r in bad:
                print(f"  {r}", file=out)
            return 1
        print(f"\nDone: {len(plan.copy)} file(s) and {len(plan.logs)} log(s) copied and verified.", file=out)
        if plan.skipped:
            print("Skipped items were not copied. Run pipeline/7_DirectoryStats/find_missing.py on the main "
                  "folder to see what needs processing.", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
