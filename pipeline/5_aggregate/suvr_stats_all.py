#!/usr/bin/env python3
"""
Aggregate SUVR results for every PET-MRI pair in the flat SUVR symlink farm into a
SINGLE CSV: one row per pair, with centiloid and all ROI SUVR columns taken from
each res/ folder's combined SUVR summary.

Input layout: a flat symlink farm as built by scripts/suvr/make_suvr_symlink_farm.py --
one symlink per '<subjid>-<session>_PET[...]' scan, pointing at the real
'<root>/<subjid>/<session>/suvr/<PET_dir>/' directory. Each of those in turn holds one
subfolder per MRI registration target:

    <PET_dir>/<subjid>_pet_<petdate>_mri_<mridate>/res/
        ..._suvr_combined_cerebellum_gm.csv   (one data row: PID, Compound, Centiloid, ROIs)

Build/refresh the farm first if it doesn't exist yet or is out of date:

    python scripts/suvr/make_suvr_symlink_farm.py \
        --source /path/to/ADRC --target /path/to/NWSI/suvr

Usage:
    python suvr_stats_all.py -sd /path/to/NWSI/suvr -o suvr_output
    python suvr_stats_all.py -sd .../NWSI/suvr --pattern suvr_combined_cerebellum   # whole-cerebellum reference
"""
import argparse
from pathlib import Path

import pandas as pd

ID_COLS = ("subject_id", "pet_date", "pet_info", "mri_date", "mri_info")


def parse_combo(name: str) -> dict:
    """Parse a combo folder name into its parts.

    Handles the base form and an optional PET reconstruction token / MRI suffix:
        320011_pet_20211014_mri_20211015
        320056_pet_20240110_128_mri_20240111
        110348_pet_9.Am2201_mri_20170811_CorMPRAGE
    """
    out = {k: None for k in ID_COLS}
    if "_pet_" not in name or "_mri_" not in name:
        return out
    subject_id, rest = name.split("_pet_", 1)
    pet_part, mri_part = rest.split("_mri_", 1)
    pet_tokens = pet_part.split("_")
    mri_tokens = mri_part.split("_")
    out["subject_id"] = subject_id
    out["pet_date"] = pet_tokens[0]
    out["pet_info"] = "_".join(pet_tokens[1:]) or None
    out["mri_date"] = mri_tokens[0]
    out["mri_info"] = "_".join(mri_tokens[1:]) or None
    return out


def _all_non_numeric(values) -> bool:
    """True if none of the values can be parsed as a float (i.e. they're labels)."""
    for v in values:
        try:
            float(v)
            return False
        except (TypeError, ValueError):
            continue
    return True


def read_summary_csv(path: Path) -> pd.DataFrame:
    """Read a per-pair SUVR CSV, handling both layouts found in res/ folders:

    * 'combined' summary (suvr_combined_*): single header row + one data row.
    * per-region table (suvr_cerebellum[_gm]): TWO header rows -- FreeSurfer label
      numbers, then region names -- followed by the data row. We use the region
      names as the column headers and drop the label-number row.
    """
    raw = pd.read_csv(path, header=None, dtype=str)
    # Two-row header iff there are >=3 lines AND the 2nd line is all non-numeric
    # (region names). A 'combined' data row has a numeric Centiloid/SUVR, so it
    # never trips this test.
    if len(raw) >= 3 and _all_non_numeric(raw.iloc[1, 1:]):
        names = raw.iloc[1].tolist()
        names[0] = "PID"
        df = raw.iloc[2:].copy()
        df.columns = names
        df = df.reset_index(drop=True)
        for c in df.columns:
            if c != "PID":
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df
    # single-header layout
    return pd.read_csv(path)


def find_res_csvs(farm_dir: Path, pattern: str):
    """Find the SUVR summary CSV in every res/ folder reachable from the flat farm.

    farm_dir is a flat directory of symlinks (one per PET scan), so we glob from
    each symlink individually rather than farm_dir itself: pathlib's '**' does not
    descend through a symlink boundary it encounters mid-walk, and every immediate
    child of farm_dir is one such symlink.
    """
    matches = []
    for pet_dir in sorted(farm_dir.iterdir()):
        if not pet_dir.is_dir():
            print(f"  WARNING: skipping {pet_dir.name} (broken symlink or not a directory)")
            continue
        for res in sorted(pet_dir.glob("**/res")):
            if not res.is_dir():
                continue
            # Anchor to the trailing type token so e.g. 'suvr_cerebellum' does not
            # also match 'suvr_cerebellum_gm' or 'suvr_combined_cerebellum'.
            hits = sorted(f for f in res.glob(f"*_{pattern}.csv") if f.is_file())
            if not hits:
                print(f"  WARNING: no '*{pattern}*.csv' in {res}")
                continue
            if len(hits) > 1:
                print(f"  NOTE: {len(hits)} matches in {res}; using {hits[0].name}")
            matches.append(hits[0])
    return matches


# The 4 SUVR patterns: 2 reference regions x 2 formats.
ALL_PATTERNS = [
    "suvr_combined_cerebellum_gm",
    "suvr_combined_cerebellum",
    "suvr_cerebellum_gm",
    "suvr_cerebellum",
]


def aggregate(farm_dir: Path, pattern: str):
    """Stack the per-pair CSV matching `pattern` from every res/ folder into one df."""
    csv_files = find_res_csvs(farm_dir, pattern)
    if not csv_files:
        print(f"  No CSV files matching '*_{pattern}.csv' found under any res/ folder.")
        return None
    print(f"  Found {len(csv_files)} '{pattern}' CSVs.")

    rows = []
    for csv_file in sorted(csv_files):
        try:
            df = read_summary_csv(csv_file)
        except Exception as e:
            print(f"  Error reading {csv_file}: {e}")
            continue
        if df.empty:
            print(f"  WARNING: {csv_file} has no data rows; skipping.")
            continue
        # Identify the pair from the combo folder name (res/ -> combo dir).
        # Assign all id columns in one block (repeated df.insert fragments the frame);
        # column order is fixed up after the concat below.
        ids = parse_combo(csv_file.parent.parent.name)
        df = df.assign(**{k: ids[k] for k in ID_COLS if k not in df.columns})
        rows.append(df)

    if not rows:
        print("  No SUVR rows collected.")
        return None

    combined = pd.concat(rows, ignore_index=True)
    id_cols = [c for c in ID_COLS if c in combined.columns]
    other = [c for c in combined.columns if c not in id_cols]
    combined = combined[id_cols + other]
    sort_keys = [c for c in ("subject_id", "pet_date", "mri_date") if c in combined.columns]
    return combined.sort_values(sort_keys).reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description="Aggregate SUVR results into per-pattern CSVs.")
    parser.add_argument("-sd", "--suvr-dir", required=True,
                        help="Flat SUVR symlink farm, as built by "
                             "scripts/suvr/make_suvr_symlink_farm.py (e.g. NWSI/suvr).")
    parser.add_argument("--pattern", default=None,
                        help="Aggregate only this single pattern instead of all 4 "
                             "(e.g. suvr_combined_cerebellum_gm).")
    parser.add_argument("-o", "--output-dir", default="suvr_output",
                        help="Directory to write the per-pattern CSVs (default: suvr_output).")
    args = parser.parse_args()

    farm_dir = Path(args.suvr_dir).resolve()
    if not farm_dir.is_dir():
        parser.error(
            f"Invalid SUVR farm directory: {farm_dir}\n"
            f"Build it first with: python scripts/suvr/make_suvr_symlink_farm.py "
            f"--source /path/to/ADRC --target {farm_dir}"
        )

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    patterns = [args.pattern] if args.pattern else ALL_PATTERNS
    written = []
    for pattern in patterns:
        print(f"\n=== {pattern} ===")
        df = aggregate(farm_dir, pattern)
        if df is None:
            continue
        out_path = out_dir / f"{pattern}.csv"
        df.to_csv(out_path, index=False)
        print(f"  Wrote {len(df)} rows x {len(df.columns)} cols -> {out_path}")
        written.append((pattern, df.shape))

    print(f"\nWrote {len(written)} CSVs to {out_dir}:")
    for pattern, (r, c) in written:
        print(f"  {pattern}.csv: {r} rows x {c} cols")


if __name__ == "__main__":
    main()
