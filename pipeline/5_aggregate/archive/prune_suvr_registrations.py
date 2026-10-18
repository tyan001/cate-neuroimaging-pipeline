from datetime import datetime
from pathlib import Path
import argparse
import logging
import shutil
import sys


"""
    Keep only the MRI registration closest in time to each PET scan.

    A PET output directory can hold one registration subfolder per
    FreeSurfer MRI session:

        <ADRC_ROOT>/<subject>/<session>/suvr/<subject>-<session>_PET[...]/
            <subject>_pet_<petdate>_mri_<mridate>[_<seq>]/   <- one per MRI
            logs/

    For every PET directory with more than one registration, this script
    keeps the one whose MRI date is nearest the PET session date and
    removes the rest.

    PET date comes from the <session> directory name (always YYYYMMDD),
    not from the registration folder name, since some of those carry
    non-date PET tokens (e.g. "9.Am2201"). MRI date is the first token
    after "_mri_" (the "_CorMPRAGE" style suffix is ignored).

    Anything ambiguous is skipped and reported, never removed:
      - a tie (two MRIs equally close to the PET date)
      - an unparseable PET or MRI date

    Dry run by default. Nothing is touched without --execute. With
    --quarantine DIR, removed folders are moved under DIR (preserving the
    ADRC-relative path) instead of being deleted, so they can be restored.

    Usage:
        python prune_suvr_registrations.py --source /path/to/NWSI/ADRC
        python prune_suvr_registrations.py --source ... --execute --quarantine /path/to/NWSI/suvr_pruned
        python prune_suvr_registrations.py --source ... --execute
"""


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("prune_suvr_registrations")


def parse_date(token: str):
    try:
        return datetime.strptime(token, "%Y%m%d")
    except ValueError:
        return None


def mri_date_of(reg_dir: Path):
    if "_mri_" not in reg_dir.name:
        return None
    return parse_date(reg_dir.name.split("_mri_", 1)[1].split("_")[0])


def find_pet_dirs(source: Path, dirname: str):
    for entry in sorted(source.glob(f"*/*/{dirname}/*")):
        if entry.name == "logs" or not entry.is_dir():
            continue
        yield entry


def plan(source: Path, dirname: str):
    """Return (to_remove, kept, skipped) lists."""
    to_remove = []
    kept = []
    skipped = []

    for pet_dir in find_pet_dirs(source, dirname):
        regs = sorted(
            d for d in pet_dir.iterdir()
            if d.is_dir() and "_pet_" in d.name and "_mri_" in d.name
        )
        if len(regs) < 2:
            continue

        # <subject>/<session>/suvr/<pet_dir>
        pet_date = parse_date(pet_dir.parent.parent.name)
        if pet_date is None:
            skipped.append((pet_dir, f"unparseable PET date {pet_dir.parent.parent.name!r}"))
            continue

        dated = [(mri_date_of(r), r) for r in regs]
        bad = [r.name for d, r in dated if d is None]
        if bad:
            skipped.append((pet_dir, f"unparseable MRI date in {bad}"))
            continue

        dated.sort(key=lambda x: abs((x[0] - pet_date).days))
        best_gap = abs((dated[0][0] - pet_date).days)
        second_gap = abs((dated[1][0] - pet_date).days)
        if best_gap == second_gap:
            tied = [r.name for d, r in dated if abs((d - pet_date).days) == best_gap]
            skipped.append((pet_dir, f"tie at {best_gap} days: {tied}"))
            continue

        keep = dated[0][1]
        kept.append((pet_dir, keep, best_gap))
        for _, r in dated[1:]:
            to_remove.append(r)

    return to_remove, kept, skipped


def main():
    parser = argparse.ArgumentParser(
        description="Keep only the MRI registration closest to each PET scan."
    )
    parser.add_argument("--source", required=True, type=Path,
                        help="ADRC root containing <subject>/<session>/suvr/...")
    parser.add_argument("--dirname", default="suvr",
                        help="Session-level SUVR folder name (default: suvr)")
    parser.add_argument("--execute", action="store_true",
                        help="Actually remove/move folders (default is a dry run)")
    parser.add_argument("--quarantine", type=Path,
                        help="Move removed folders here instead of deleting them")
    args = parser.parse_args()

    source = args.source.resolve()
    if not source.is_dir():
        log.error("--source %s is not a directory", source)
        sys.exit(1)

    to_remove, kept, skipped = plan(source, args.dirname)

    for pet_dir, keep, gap in kept:
        log.info("KEEP   %s  (%d days)", keep.relative_to(source), gap)
    for r in to_remove:
        log.info("REMOVE %s", r.relative_to(source))
    for pet_dir, reason in skipped:
        log.warning("SKIP   %s: %s", pet_dir.relative_to(source), reason)

    if args.execute:
        for r in to_remove:
            if args.quarantine:
                dest = args.quarantine / r.relative_to(source)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(r), str(dest))
            else:
                shutil.rmtree(r)

    log.info("---- summary ----")
    log.info("PET dirs pruned:    %d", len(kept))
    log.info("registrations kept: %d", len(kept))
    log.info("registrations %s: %d",
             "moved  " if args.quarantine else "removed", len(to_remove))
    log.info("PET dirs skipped:   %d", len(skipped))
    if not args.execute:
        log.info("(dry run -- no changes were made; pass --execute to apply)")


if __name__ == "__main__":
    main()
