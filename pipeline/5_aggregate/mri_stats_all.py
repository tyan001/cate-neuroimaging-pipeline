#!/usr/bin/env python3
"""
Aggregate FreeSurfer morphometry for every recon subject under a root directory
(e.g. NWSI/ADRC) into SEPARATE per-measure CSVs (one row per recon subject):

    aparc_thickness.csv   cortical thickness, left + right hemispheres
    aparc_volume.csv      cortical volume,    left + right hemispheres
    aseg_stats.csv        subcortical segmentation volumes (aseg.stats)
    wmparc.csv            white-matter parcellation volumes (wmparc.stats)
    hippocampus.csv       hippocampal subfield volumes, left + right (segmentHA)

Layout assumed (the existing pipeline output):
    <root>/<subjid>/<session>/freesurfer741/<subjid>-<scandate>_<type>/{stats,mri}/...

Requires a working FreeSurfer environment (FREESURFER_HOME set, valid license) for
the aseg/aparc/wmparc tables; the hippocampus table is parsed directly from the
per-subject mri/*.hippoSfVolumes-*.txt files.

Usage:
    python mri_stats_all.py -rd /data/ADRC -o mri_output
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

import pandas as pd

SUBJECT_RE = re.compile(r"^(?P<subject_id>[^-]+)-(?P<scan_date>\d{8})_(?P<scan_type>.+)$")


def find_all_subjects(root_dir: Path):
    """Find every freesurfer741/<subject> folder under root (excluding fsaverage)."""
    subject_paths, seen = [], set()
    for fs_dir in root_dir.rglob("freesurfer741"):
        if not fs_dir.is_dir():
            continue
        for subj in fs_dir.iterdir():
            if subj.is_dir() and subj.name != "fsaverage" and subj.name not in seen:
                if (subj / "stats").is_dir():
                    subject_paths.append(subj)
                    seen.add(subj.name)
    return sorted(subject_paths, key=lambda p: p.name)


def run_table(cmd: str, subjects_dir: Path, out_file: Path):
    print(f"Running: {cmd}")
    subprocess.run(cmd, shell=True, cwd=subjects_dir, check=False)
    if not out_file.exists():
        print(f"  WARNING: {out_file.name} was not produced.")
        return None
    df = pd.read_csv(out_file, sep="\t")
    if df.empty or df.columns.size == 0:
        print(f"  WARNING: {out_file.name} is empty.")
        return None
    # First column is the subject id (header varies by tool); normalise it.
    df = df.rename(columns={df.columns[0]: "subject"})
    df["subject"] = df["subject"].astype(str).str.replace(".nii", "", regex=False)
    return df


def add_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Prepend subject_id / scan_date / scan_type parsed from the subject name."""
    parsed = df["subject"].str.extract(SUBJECT_RE)
    df = df.copy()
    for col in ("subject_id", "scan_date", "scan_type"):
        df.insert(df.columns.get_loc("subject"), col, parsed[col])
    return df.sort_values("subject").reset_index(drop=True)


def parse_hippo_file(txt: Path) -> dict:
    """Parse a '<name> <volume>' hippoSfVolumes/amygNucVolumes txt into a dict."""
    out = {}
    for line in txt.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                out[parts[0]] = float(parts[1])
            except ValueError:
                pass
    return out


def build_subfield_table(subject_paths, file_glob: str, label: str) -> pd.DataFrame:
    """One row per subject: lh_/rh_ subfield volumes from per-hemi txt files.

    file_glob uses '{hemi}', e.g. '{hemi}.hippoSfVolumes-*.txt'.
    """
    rows = []
    for sp in subject_paths:
        mri = sp / "mri"
        row = {"subject": sp.name}
        found = False
        for hemi in ("lh", "rh"):
            hits = sorted(mri.glob(file_glob.format(hemi=hemi)))
            if not hits:
                continue
            found = True
            for name, vol in parse_hippo_file(hits[0]).items():
                row[f"{hemi}_{name}"] = vol
        if found:
            rows.append(row)
        else:
            print(f"  NOTE: no {label} files for {sp.name}")
    if not rows:
        return None
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="Aggregate FreeSurfer MRI stats into per-measure CSVs.")
    parser.add_argument("-rd", "--root-dir", required=True,
                        help="Root directory to search for freesurfer741 folders (e.g. NWSI/ADRC).")
    parser.add_argument("-o", "--output-dir", default="mri_output",
                        help="Directory to write the per-measure CSVs (default: mri_output).")
    args = parser.parse_args()

    root_dir = Path(args.root_dir).resolve()
    if not root_dir.is_dir():
        parser.error(f"Invalid root directory: {root_dir}")

    subject_paths = find_all_subjects(root_dir)
    if not subject_paths:
        print("No recon subjects found under any freesurfer741 directory.")
        return
    print(f"Found {len(subject_paths)} recon subjects.")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    with tempfile.TemporaryDirectory() as tmp:
        subjects_dir = Path(tmp)
        subjects = []
        for sp in subject_paths:
            link = subjects_dir / sp.name
            try:
                link.symlink_to(sp)
                subjects.append(sp.name)
            except OSError as e:
                print(f"  Failed to symlink {sp}: {e}")
        os.environ["SUBJECTS_DIR"] = str(subjects_dir)
        subj_arg = " ".join(subjects)

        # --- aseg subcortical volumes ---
        df = run_table(f"asegstats2table --subjects {subj_arg} --meas volume --skip "
                       f"--tablefile aseg_stats.txt", subjects_dir, subjects_dir / "aseg_stats.txt")
        if df is not None:
            add_ids(df).to_csv(out_dir / "aseg_stats.csv", index=False)
            written.append("aseg_stats.csv")

        # --- wmparc white-matter volumes ---
        df = run_table(f"asegstats2table --subjects {subj_arg} --meas volume --skip "
                       f"--statsfile wmparc.stats --all-segs --tablefile wmparc.txt",
                       subjects_dir, subjects_dir / "wmparc.txt")
        if df is not None:
            add_ids(df).to_csv(out_dir / "wmparc.csv", index=False)
            written.append("wmparc.csv")

        # --- aparc cortical volume (lh + rh) ---
        lh = run_table(f"aparcstats2table --subjects {subj_arg} --hemi lh --meas volume --skip "
                       f"--tablefile aparc_volume_lh.txt", subjects_dir, subjects_dir / "aparc_volume_lh.txt")
        rh = run_table(f"aparcstats2table --subjects {subj_arg} --hemi rh --meas volume --skip "
                       f"--tablefile aparc_volume_rh.txt", subjects_dir, subjects_dir / "aparc_volume_rh.txt")
        if lh is not None or rh is not None:
            merged = lh if rh is None else (rh if lh is None else lh.merge(rh, on="subject", how="outer"))
            add_ids(merged).to_csv(out_dir / "aparc_volume.csv", index=False)
            written.append("aparc_volume.csv")

        # --- aparc cortical thickness (lh + rh) ---
        lh = run_table(f"aparcstats2table --subjects {subj_arg} --hemi lh --meas thickness --skip "
                       f"--tablefile aparc_thickness_lh.txt", subjects_dir, subjects_dir / "aparc_thickness_lh.txt")
        rh = run_table(f"aparcstats2table --subjects {subj_arg} --hemi rh --meas thickness --skip "
                       f"--tablefile aparc_thickness_rh.txt", subjects_dir, subjects_dir / "aparc_thickness_rh.txt")
        if lh is not None or rh is not None:
            merged = lh if rh is None else (rh if lh is None else lh.merge(rh, on="subject", how="outer"))
            add_ids(merged).to_csv(out_dir / "aparc_thickness.csv", index=False)
            written.append("aparc_thickness.csv")

    # --- hippocampal subfields & amygdala nuclei (parsed directly) ---
    hippo = build_subfield_table(subject_paths, "{hemi}.hippoSfVolumes-*.txt", "hippoSfVolumes")
    if hippo is not None:
        add_ids(hippo).to_csv(out_dir / "hippocampus.csv", index=False)
        written.append("hippocampus.csv")

    amyg = build_subfield_table(subject_paths, "{hemi}.amygNucVolumes-*.txt", "amygNucVolumes")
    if amyg is not None:
        add_ids(amyg).to_csv(out_dir / "amygdala.csv", index=False)
        written.append("amygdala.csv")

    print(f"\nWrote {len(written)} CSVs to {out_dir}:")
    for name in written:
        df = pd.read_csv(out_dir / name)
        print(f"  {name}: {df.shape[0]} rows x {df.shape[1]} cols")


if __name__ == "__main__":
    main()
