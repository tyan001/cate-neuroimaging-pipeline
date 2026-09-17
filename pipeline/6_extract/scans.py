#!/usr/bin/env python3
"""Locate scans in the organized dataset by subject ID and session date.

Used by viewer.py, and usable on its own:

    python3 scans.py 900001                      # sessions, with the T1w/PET/CT in each
    python3 scans.py 900001 01/15/2020           # every volume in that session
    python3 scans.py 900001 01/15/2020 -t pet    # just the path(s), one per line

Layout contract (docs/04-data-organization.md):

    <root>/<pid>/<YYYYMMDD>/anat/<pid>-<YYYYMMDD>_T1w.nii
    <root>/<pid>/<YYYYMMDD>/pet/<pid>-<YYYYMMDD>_PET.nii     (+ _PET_128, _PET_a, ... variants)
    <root>/<pid>/<YYYYMMDD>/ct/<pid>-<YYYYMMDD>_CT.nii

The dataset root comes from --root or $ADRC_ROOT.
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ADRC_ROOT = os.environ.get("ADRC_ROOT", "")

VOLUME_SUFFIXES = (".nii", ".nii.gz", ".mgz", ".mgh")

# kind -> (session subfolder, filename suffix after "<pid>-<date>")
SCAN_KINDS = {
    "t1w": ("anat", "_T1w"),
    "mprage": ("anat", "_CorMPRAGE"),
    "pet": ("pet", "_PET"),
    "ct": ("ct", "_CT"),
}

_DATE_FORMATS = ("%Y%m%d", "%m/%d/%Y", "%Y-%m-%d")


def parse_date(text: str) -> str:
    """Normalize MM/DD/YYYY, YYYY-MM-DD or YYYYMMDD to the YYYYMMDD folder name."""
    text = text.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date {text!r}; use MM/DD/YYYY or YYYYMMDD")


def pretty_date(folder: str) -> str:
    return f"{folder[:4]}-{folder[4:6]}-{folder[6:]}"


def is_volume(path: Path) -> bool:
    return path.name.endswith(VOLUME_SUFFIXES)


def resolve_root(root: str | os.PathLike | None) -> Path:
    root = root or ADRC_ROOT
    if not root:
        raise SystemExit("No dataset root: pass --root or export ADRC_ROOT")
    path = Path(root).expanduser()
    if not path.is_dir():
        raise SystemExit(f"Dataset root does not exist: {path}")
    return path


def list_subjects(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir() if p.is_dir() and p.name != "logs")


def find_scans(root: Path, pid: str, date: str, kind: str) -> list[Path]:
    """All scans of `kind` in one session, exact name first, then variants (_PET_128, ...)."""
    subdir, suffix = SCAN_KINDS[kind]
    folder = root / pid / date / subdir
    if not folder.is_dir():
        return []
    stem = f"{pid}-{date}{suffix}"
    pattern = re.compile(re.escape(stem) + r"(_[^.]+)?\.(nii|nii\.gz|mgz)$")
    matches = [p for p in folder.iterdir() if pattern.fullmatch(p.name)]
    # Sorting on (has-variant, name) puts the plain <stem>.nii ahead of its variants.
    return sorted(matches, key=lambda p: (p.name.split(".")[0] != stem, p.name))


@dataclass
class Session:
    date: str  # YYYYMMDD
    path: Path
    scans: dict[str, list[Path]] = field(default_factory=dict)

    @property
    def modality(self) -> str:
        if self.scans.get("pet"):
            return "PET"
        if self.scans.get("t1w") or self.scans.get("mprage") or (self.path / "anat").is_dir():
            return "MRI"
        if (self.path / "pet").is_dir():
            return "PET"
        return "?"

    @property
    def subfolders(self) -> list[str]:
        return sorted(p.name for p in self.path.iterdir() if p.is_dir())


def list_sessions(root: Path, pid: str) -> list[Session]:
    subject = root / pid
    if not subject.is_dir():
        return []
    sessions = []
    for child in sorted(subject.iterdir()):
        if not (child.is_dir() and re.fullmatch(r"\d{8}", child.name)):
            continue
        scans = {kind: find_scans(root, pid, child.name, kind) for kind in SCAN_KINDS}
        sessions.append(Session(child.name, child, scans))
    return sessions


def session_volumes(root: Path, pid: str, date: str) -> dict[str, list[Path]]:
    """Every viewable volume in a session, grouped by its folder relative to the session."""
    session = root / pid / date
    groups: dict[str, list[Path]] = {}
    for dirpath, dirnames, filenames in os.walk(session):
        dirnames.sort()
        vols = sorted(Path(dirpath) / f for f in filenames if f.endswith(VOLUME_SUFFIXES))
        if vols:
            groups[str(Path(dirpath).relative_to(session))] = vols
    return groups


def _size(path: Path) -> str:
    n = path.stat().st_size
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find T1w / PET / CT scans by subject and date.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n\n")[1],
    )
    parser.add_argument("subject", help="subject ID, e.g. 900001")
    parser.add_argument("date", nargs="?", help="session date: MM/DD/YYYY or YYYYMMDD")
    parser.add_argument("-t", "--type", choices=sorted(SCAN_KINDS), help="print only this scan type's path(s)")
    parser.add_argument("-r", "--root", help="dataset root (default: $ADRC_ROOT)")
    args = parser.parse_args()

    root = resolve_root(args.root)
    pid = args.subject.strip()
    if not (root / pid).is_dir():
        sys.exit(f"Subject {pid} not found under {root}")

    if args.date is None:
        if args.type:
            parser.error("--type needs a date; omit it to list sessions")
        sessions = list_sessions(root, pid)
        if not sessions:
            sys.exit(f"Subject {pid} has no session folders")
        print(f"{pid}: {len(sessions)} session(s) in {root / pid}\n")
        for s in sessions:
            print(f"  {pretty_date(s.date)}  {s.modality:<3}  [{', '.join(s.subfolders)}]")
            for kind, paths in s.scans.items():
                for p in paths:
                    print(f"      {kind:<6} {p.name}  ({_size(p)})")
        return

    try:
        date = parse_date(args.date)
    except ValueError as e:
        sys.exit(str(e))
    if not (root / pid / date).is_dir():
        dates = ", ".join(pretty_date(s.date) for s in list_sessions(root, pid))
        sys.exit(f"No session {pretty_date(date)} for {pid}. Available: {dates or 'none'}")

    if args.type:
        paths = find_scans(root, pid, date, args.type)
        if not paths:
            sys.exit(f"No {args.type} scan in {root / pid / date / SCAN_KINDS[args.type][0]}")
        print("\n".join(str(p) for p in paths))
        return

    for group, vols in session_volumes(root, pid, date).items():
        print(f"{group}/")
        for p in vols:
            print(f"    {p.name}  ({_size(p)})")


if __name__ == "__main__":
    main()
