from pathlib import Path
import argparse
import logging
import sys


"""
    Build a "symlink farm" for SUVR output: a single flat directory
    containing one symlink per processed PET/SUVR scan, pointing back at
    the real output directory.

    Why:
    SUVR output is stored nested as

        <ADRC_ROOT>/<subject>/<session>/suvr/<subject>-<session>_PET[...]/

    e.g. NWSI/ADRC/110004/20150527/suvr/110004-20150527_PET

    alongside a sibling "logs/" folder. That nested layout is what
    prepare_suvr_folder.py and friends expect. This script does NOT move
    or copy any data -- it only creates symlinks in a separate flat
    folder, so the nested layout stays untouched. Point downstream
    aggregation scripts at the flat folder instead of walking the nested
    tree, e.g.:

        for d in /mnt/backup/dev/NWSI/suvr/*/; do
            ls "$d"/*/res/*_suvr_cerebellum_gm.csv
        done

    Naming is less uniform than FreeSurfer's: most scans are named
    "<subject>-<session>_PET", but a number of re-processed/alternate
    acquisitions use suffixes like "_PET_128", "_PET_256", "_PET_a",
    "_PET_BIG", "_PET_128a". These are genuinely distinct outputs for
    the same subject/session (e.g. a low-res and high-res reprocessing
    living side by side), not duplicates, so every one of them gets its
    own symlink -- nothing is collapsed or deduplicated by session.

    "logs" (per-session SUVR processing logs, not scan output) is always
    excluded.

    Each PET output directory itself contains one subfolder per MRI
    registration target, e.g.

        110004-20150527_PET/110004_pet_20150527_mri_20170215/res/*.csv

    because a single PET scan can be registered against more than one
    FreeSurfer MRI session. This script symlinks at the "<subject>-
    <session>_PET[...]" level (matching the nested nesting used
    everywhere else) and leaves that registration-target layer alone --
    downstream code can glob into */res/*.csv as needed.

    Usage:
        python make_suvr_symlink_farm.py \\
            --source /mnt/backup/dev/NWSI/ADRC \\
            --target /mnt/backup/dev/NWSI/suvr

        python make_suvr_symlink_farm.py --source ... --target ... --dry-run
"""


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("make_suvr_symlink_farm")

EXCLUDED_NAMES = {"logs"}


def find_scan_dirs(source: Path, dirname: str):
    """
    Yield every real PET/SUVR scan output directory under
    source/*/*/<dirname>/*, skipping "logs" and anything that isn't a
    directory.
    """
    pattern = f"*/*/{dirname}/*"
    for entry in sorted(source.glob(pattern)):
        if entry.name in EXCLUDED_NAMES:
            continue
        if not entry.is_dir():
            continue
        yield entry


def build_farm(source: Path, target: Path, dirname: str, dry_run: bool, force: bool):
    target.mkdir(parents=True, exist_ok=True)

    created = 0
    already_ok = 0
    skipped_collision = 0
    replaced = 0
    unexpected_naming = []

    seen: dict[str, Path] = {}

    for scan_dir in find_scan_dirs(source, dirname):
        name = scan_dir.name
        link_path = target / name
        real_source = scan_dir.resolve()

        if "_PET" not in name:
            unexpected_naming.append(name)

        if name in seen and seen[name] != real_source:
            log.warning(
                "Name collision for %s: %s vs %s (keeping first, skipping second)",
                name, seen[name], real_source,
            )
            skipped_collision += 1
            continue
        seen[name] = real_source

        if link_path.is_symlink():
            current_target = link_path.resolve()
            if current_target == real_source:
                already_ok += 1
                continue
            if not force:
                log.warning(
                    "%s already links elsewhere (%s != %s); use --force to overwrite",
                    link_path, current_target, real_source,
                )
                skipped_collision += 1
                continue
            if dry_run:
                log.info("[dry-run] would replace %s -> %s", link_path, real_source)
            else:
                link_path.unlink()
                link_path.symlink_to(real_source)
            replaced += 1
            continue

        if link_path.exists():
            log.warning(
                "%s exists and is not a symlink (real file/dir) -- skipping to avoid clobbering it",
                link_path,
            )
            skipped_collision += 1
            continue

        if dry_run:
            log.info("[dry-run] would create %s -> %s", link_path, real_source)
        else:
            link_path.symlink_to(real_source)
        created += 1

    log.info("---- summary ----")
    log.info("created:            %d", created)
    log.info("replaced:           %d", replaced)
    log.info("already up to date: %d", already_ok)
    log.info("skipped (conflict): %d", skipped_collision)
    if unexpected_naming:
        log.warning(
            "%d entries did not contain '_PET' in their name (check these are real scans): %s",
            len(unexpected_naming), unexpected_naming,
        )
    if dry_run:
        log.info("(dry run -- no changes were made)")

    return skipped_collision == 0


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build a flat symlink farm of SUVR/PET scan output directories."
    )
    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="Root ADRC-style directory containing <subject>/<session>/<dirname>/<subject-session>_PET...",
    )
    parser.add_argument(
        "--target",
        required=True,
        type=Path,
        help="Flat directory to populate with symlinks (created if missing)",
    )
    parser.add_argument(
        "--dirname",
        default="suvr",
        help="Exact SUVR output folder name to target at the session level (default: suvr)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without creating/modifying any symlinks",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing symlinks that point somewhere else",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    source = args.source.resolve()
    if not source.is_dir():
        log.error("--source %s is not a directory", source)
        sys.exit(1)

    ok = build_farm(
        source=source,
        target=args.target,
        dirname=args.dirname,
        dry_run=args.dry_run,
        force=args.force,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
