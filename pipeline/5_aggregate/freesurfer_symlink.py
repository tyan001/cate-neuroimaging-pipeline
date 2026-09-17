from pathlib import Path
import argparse
import logging
import sys


"""
    Build a "symlink farm": a single flat directory containing one symlink
    per processed FreeSurfer subject/session, pointing back at the real
    recon-all output directory.

    Why:
    The pipeline stores FreeSurfer output nested as

        <ADRC_ROOT>/<subject>/<session>/<fs_dirname>/<subject>-<session>_<sequence>/

    which is what recon-all/mri_processing.py expect (SUBJECTS_DIR-relative
    tools, sibling anat/pet/suvr/sitedata_mri folders per session). That
    layout is awkward for one-off stats aggregation with asegstats2table /
    aparcstats2table, which want every subject directory as an immediate
    child of a single SUBJECTS_DIR.

    This script does NOT move or copy any data. It only creates symlinks in
    a separate flat folder, so the nested layout the rest of the pipeline
    depends on is untouched. Point FreeSurfer's stats tools at the flat
    folder via SUBJECTS_DIR, e.g.:

        export SUBJECTS_DIR=/mnt/backup/dev/NWSI/freesurfer
        asegstats2table --subjects $(ls $SUBJECTS_DIR) -t all_aseg.csv

    Subject/session leaf directories are named "<subject>-<session>_<seq>",
    e.g. "110004-20090603_T1w" or "110014-20200312_CorMPRAGE" -- both
    sequence naming conventions found in the data are included by default
    since the match is by directory position, not by suffix.

    "fsaverage" (FreeSurfer's bundled reference subject, duplicated inside
    every freesurfer741 folder in newer sessions) is always excluded -- it
    is not real subject data and would collide across subjects since the
    name is identical everywhere.

    Usage:
        python make_symlink_farm.py \\
            --source /mnt/backup/dev/NWSI/ADRC \\
            --target /mnt/backup/dev/NWSI/freesurfer

        python make_symlink_farm.py --source ... --target ... --dry-run
"""


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("make_symlink_farm")

EXCLUDED_NAMES = {"fsaverage"}


def find_subject_dirs(source: Path, fs_dirname: str):
    """
    Yield every real subject/session output directory under
    source/*/*/<fs_dirname>/*, skipping fsaverage and anything that
    isn't a directory (defensive -- recon-all only ever puts dirs here,
    but a stray file should not crash the run).
    """
    pattern = f"*/*/{fs_dirname}/*"
    for entry in sorted(source.glob(pattern)):
        if entry.name in EXCLUDED_NAMES:
            continue
        if not entry.is_dir():
            continue
        yield entry


def build_farm(source: Path, target: Path, fs_dirname: str, dry_run: bool, force: bool):
    target.mkdir(parents=True, exist_ok=True)

    created = 0
    already_ok = 0
    skipped_collision = 0
    replaced = 0
    by_sequence = {}

    seen: dict[str, Path] = {}

    for subject_dir in find_subject_dirs(source, fs_dirname):
        name = subject_dir.name
        link_path = target / name
        real_source = subject_dir.resolve()

        # sequence is whatever follows the last underscore, e.g. T1w / CorMPRAGE
        sequence = name.rsplit("_", 1)[-1] if "_" in name else "unknown"
        by_sequence[sequence] = by_sequence.get(sequence, 0) + 1

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
    for sequence, count in sorted(by_sequence.items()):
        log.info("  sequence %-12s %d", sequence, count)
    if dry_run:
        log.info("(dry run -- no changes were made)")

    return skipped_collision == 0


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build a flat symlink farm of FreeSurfer subject/session directories."
    )
    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="Root ADRC-style directory containing <subject>/<session>/<fs_dirname>/<subject-session>",
    )
    parser.add_argument(
        "--target",
        required=True,
        type=Path,
        help="Flat directory to populate with symlinks (created if missing)",
    )
    parser.add_argument(
        "--fs-dirname",
        default="freesurfer741",
        help="Exact FreeSurfer output folder name to target (default: freesurfer741). "
             "Failed/alternate runs such as freesurfer741_t are excluded by default "
             "since this must match exactly.",
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
        fs_dirname=args.fs_dirname,
        dry_run=args.dry_run,
        force=args.force,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
