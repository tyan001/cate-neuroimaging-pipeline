#!/usr/bin/env python3
"""Report MRI and PET scans that have not been processed. Changes nothing.

    python3 find_missing.py --root /path/to/ADRC
    python3 find_missing.py --root /path/to/ADRC --csv missing.csv       # one row per scan
    python3 find_missing.py --root /path/to/ADRC --all                   # also list complete scans
    python3 find_missing.py --root /path/to/ADRC --subject 930119
    ADRC_ROOT=/path/to/ADRC python3 find_missing.py

See inventory.py for what each status means. process_missing.py acts on the same statuses.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from pathlib import Path

from inventory import MRI_TODO, PET_TODO, MriState, PetState, inventory

MRI_ACTION = {
    MriState.NO_FREESURFER: "run recon-all + hippocampus",
    MriState.NO_HIPPOCAMPUS: "run hippocampus",
    MriState.RECON_FAILED: "manual: check log, delete folder, rerun",
    MriState.RECON_INCOMPLETE: "manual: wait, or delete folder and rerun",
    MriState.WRONG_SESSION: "manual: move or delete the stray file",
    MriState.COMPLETE: "",
}
PET_ACTION = {
    PetState.WAITING_FOR_MRI: "wait for an MRI",
    PetState.WAITING_FOR_FREESURFER: "run the MRI step first",
    PetState.NO_SUVR: "run SUVR",
    PetState.INCOMPLETE_SUVR: "run SUVR (resumes)",
    PetState.BAD_NAME: "manual: rename file",
    PetState.WRONG_SESSION: "manual: move or delete the stray file",
    PetState.COMPLETE: "",
}
CSV_FIELDS = ["modality", "subject", "session", "scan", "status", "action", "paired_mri", "detail"]


def rows(mri_records, pet_records):
    for r in mri_records:
        yield {"modality": "MRI", "subject": r.subject, "session": r.session, "scan": r.scan.name,
               "status": r.state.value, "action": MRI_ACTION[r.state], "paired_mri": "", "detail": r.detail}
    for r in pet_records:
        yield {"modality": "PET", "subject": r.subject, "session": r.session, "scan": r.scan.name,
               "status": r.state.value, "action": PET_ACTION[r.state],
               "paired_mri": r.mri.name if r.mri else "", "detail": r.detail}


def print_section(title, records, states, actions, show_all):
    counts = Counter(r.state for r in records)
    print(f"\n=== {title}: {len(records)} scan(s) ===")
    for state in states:
        print(f"  {state.value:<24} {counts[state]:>5}   {actions[state]}")
    for state in states:
        if counts[state] == 0 or (state.value == "complete" and not show_all):
            continue
        print(f"\n--- {state.value} ({counts[state]}) ---")
        for r in records:
            if r.state is state:
                line = f"  {r.subject}/{r.session}/{r.scan.parent.name}/{r.scan.name}"
                print(f"{line}   {r.detail}" if r.detail else line)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=os.environ.get("ADRC_ROOT"),
                        help="ADRC directory, one folder per subject (default: $ADRC_ROOT)")
    parser.add_argument("--subject", action="append", metavar="ID", help="Only this subject (repeatable)")
    parser.add_argument("--csv", type=Path, help="Write one row per scan to this file")
    parser.add_argument("--all", action="store_true", help="Also list complete scans")
    args = parser.parse_args(argv)

    if args.root is None:
        parser.error("--root is required unless $ADRC_ROOT is set")
    if not args.root.is_dir():
        print(f"Not a directory: {args.root}", file=sys.stderr)
        return 1
    try:
        mri, pet = inventory(args.root.resolve(), args.subject)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    print(f"Root: {args.root.resolve()}")
    print_section("MRI", mri, list(MriState), MRI_ACTION, args.all)
    print_section("PET", pet, list(PetState), PET_ACTION, args.all)

    n_mri = sum(r.state in MRI_TODO for r in mri)
    n_pet = sum(r.state in PET_TODO for r in pet)
    n_after = sum(r.state is PetState.WAITING_FOR_FREESURFER for r in pet)
    print(f"\nprocess_missing.py would run: {n_mri} MRI, {n_pet} PET "
          f"(+{n_after} PET waiting on their MRI's recon-all)")

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows(mri, pet))
        print(f"Wrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
