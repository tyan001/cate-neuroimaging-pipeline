#!/usr/bin/env python3
"""Summarize NWSI data: modality folder counts under ADRC and processed-output link counts."""

import argparse
import os
from pathlib import Path

FOLDER_NAMES = ["anat", "ct", "pet", "modalities"]
LINK_DIRS = ["freesurfer_link", "suvr_link"]


def count_adrc_folders(adrc: Path) -> dict[str, int]:
    """Count folders at ADRC/<subject>/<date>/<folder>."""
    return {
        name: sum(1 for p in adrc.glob(f"*/*/{name}") if p.is_dir())
        for name in FOLDER_NAMES
    }


def count_links(link_dir: Path) -> tuple[int, int]:
    """Return (total entries, broken symlinks) in a link folder."""
    entries = list(link_dir.iterdir())
    broken = sum(1 for p in entries if p.is_symlink() and not p.exists())
    return len(entries), broken


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = os.environ.get("ADRC_ROOT") 
    parser.add_argument(
        "-i", "--input",
        type=Path,
        default=Path(default_root) if default_root else None,
        required=default_root is None,
        help="root folder containing ADRC, freesurfer_link and suvr_link "
             "(default: $ADRC_ROOT)",
    )
    args = parser.parse_args()

    root = args.input
    adrc = root / "ADRC"
    if not adrc.is_dir():
        parser.error(f"ADRC folder not found: {adrc}")

    n_subjects = sum(1 for p in adrc.iterdir() if p.is_dir())
    print(f"NWSI root: {root}")
    print(f"Subjects in ADRC: {n_subjects}")

    print("\n== ADRC folders (ADRC/<subject>/<date>/<folder>) ==")
    for name, n in count_adrc_folders(adrc).items():
        print(f"  {name:<12} {n:6d}")

    print("\n== Processed outputs ==")
    for name in LINK_DIRS:
        link_dir = root / name
        if not link_dir.is_dir():
            print(f"  {name:<16} missing")
            continue
        total, broken = count_links(link_dir)
        print(f"  {name:<16} {total:6d}  (broken links: {broken})")


if __name__ == "__main__":
    main()
