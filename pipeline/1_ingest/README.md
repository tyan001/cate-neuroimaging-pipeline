# 1. Ingest

Turns a raw vendor delivery into the subject/date/modality layout the rest of the pipeline reads.

Input is already NIfTI — there is no DICOM conversion anywhere in this project. Delivery folders are
named `MRI_<subjid>[-<session>]_<MMDDYYYY>` / `PET_<subjid>-<session>_<MMDDYYYY>`.

Full walkthrough: [docs/02-mri-processing.md](../../docs/02-mri-processing.md#stage-1--ingest).

| Script | Purpose |
|---|---|
| `download.py` | Fetch and extract archives listed in a CSV |
| `unzip_files.sh` | Extract a directory of zips (alternative to the above) |
| `prefix.py` | Bulk-add `MRI_` / `PET_` prefixes to folder names |
| `dropbox_mri_to_bids.py` | MRI delivery → `ADRC/<subj>/<date>/{anat,modalities}/` |
| `dropbox_pet_to_bids.py` | PET delivery → `ADRC/<subj>/<date>/{pet,ct}/` |

---

## download.py

```bash
python3 download.py links.csv --type MRI|PET [--output-dir /path/to/batch]
```

Writes into a `<type>` subfolder (`MRI/` or `PET/`) under `--output-dir`, or the current directory
if omitted.

CSV needs `name` and `link` columns — see [examples/dropbox_links.csv](../../examples/dropbox_links.csv).
Downloads with `curl`, unzips, deletes the archive. Output goes to `<csv_dir>/MRI/` or `<csv_dir>/PET/`.

## unzip_files.sh

```bash
bash unzip_files.sh /path/to/zips
```

Extracts each `foo.zip` into a sibling `foo/`. Use when you already have the archives.

## prefix.py

```bash
python3 prefix.py /path/to/folders --prefix MRI_ [--dry-run]
```

Renames immediate subfolders, skipping any already prefixed — safe to re-run. `--prefix` defaults to
`MRI_`. Needed for sites that deliver without the modality prefix (for us, the `320` UF subjects).

## dropbox_mri_to_bids.py

```bash
python3 dropbox_mri_to_bids.py /path/to/MRI --target_dir /path/to/batch
```

```
<target>/ADRC/<subjid>/<YYYYMMDD>/
├── anat/        <subjid>-<YYYYMMDD>_T1w.nii   (or _CorMPRAGE.nii)
└── modalities/  every original file, untouched
```

Prefers a `T1` series, falls back to `Cor_MPRAGE`. Logs to `<target>/logs/mri_bids_logs/`.

> The chosen T1 is latched per **subject**, not per session — convert multi-session subjects one
> session at a time, then verify with `pipeline/5_aggregate/anat_report.py`.

## dropbox_pet_to_bids.py

```bash
python3 dropbox_pet_to_bids.py /path/to/PET --target_dir /path/to/batch
```

```
<target>/ADRC/<subjid>/<YYYYMMDD>/
├── pet/  <subjid>-<YYYYMMDD>_PET.nii
└── ct/   <subjid>-<YYYYMMDD>_CT.nii
```

PET series are matched by the substrings `mean_5mmblur`, `PET_6mmblur`, `PET_3mmblur`, `PET_256`;
CT by `amyloid_pet_ct`, `pet_ct`. **These are site- and scanner-specific — edit them for your data.**
Logs to `<target>/logs/pet_bids_logs/`.

---

**Note:** the output cohort directory is the string literal `ADRC` in both converters. Change it
there if you need a different name.
