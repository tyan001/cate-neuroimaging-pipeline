# 5. Aggregation and reporting

Walks the assembled dataset and collapses it into flat, study-level CSVs — plus utilities for
generating shareable derivatives and inventory reports.

| Script | Output | Row = | Needs |
|---|---|---|---|
| `mri_stats_all.py` | 6 per-measure CSVs | one recon MRI subject | FreeSurfer on PATH |
| `suvr_stats_all.py` | one CSV per pattern (4 total) | one PET–MRI pair | pandas only |
| `mri_site_data.py` | `sitedata_mri/` per session | — | FreeSurfer on PATH |
| `anat_report.py` | inventory CSV of all `anat/` files | one scan | pandas |
| `pet_report.py` | inventory CSV of all `pet/` folders | one file | stdlib |
| `ConcatenateSubregionsResults` | concatenated `.stats` across subjects | one subject | FreeSurfer (vendored utility) |

Expected input layout: [docs/04-data-organization.md](../../docs/04-data-organization.md).

---

## mri_stats_all.py

```bash
source $FREESURFER_HOME/SetUpFreeSurfer.sh
python3 mri_stats_all.py -rd /path/to/ADRC -o mri_output
```

1. Recursively finds every `freesurfer741/<subject>` folder (skipping `fsaverage` and any subject
   without `stats/`).
2. Symlinks them into a temporary `SUBJECTS_DIR` so FreeSurfer's table tools see one flat subjects
   directory — necessary because recons are scattered one per session.
3. Runs the table tools and writes six CSVs, one row per subject, each prefixed with
   `subject_id, scan_date, scan_type, subject`.

| File | Contents | Method |
|---|---|---|
| `aseg_stats.csv` | subcortical volumes | `asegstats2table` |
| `wmparc.csv` | white-matter parcellation volumes | `asegstats2table --statsfile wmparc.stats --all-segs` |
| `aparc_volume.csv` | cortical volume, L+R merged | `aparcstats2table --meas volume` |
| `aparc_thickness.csv` | cortical thickness, L+R merged | `aparcstats2table --meas thickness` |
| `hippocampus.csv` | 22 hippocampal subfields per hemisphere | parsed from `mri/{lh,rh}.hippoSfVolumes-*.txt` |
| `amygdala.csv` | 10 amygdala nuclei per hemisphere | parsed from `mri/{lh,rh}.amygNucVolumes-*.txt` |

Columns keep native FreeSurfer names (`Left-Hippocampus`, `lh_entorhinal_thickness`,
`wm-lh-bankssts`); hippocampus and amygdala use `lh_<subfield>` / `rh_<nucleus>`.

**Notes.** The aseg/aparc/wmparc tables shell out to FreeSurfer and need a valid license. The
hippocampus and amygdala tables do **not** — they read the per-subject text files directly, which
works even without `quantifyHippocampalSubfields.sh` installed. Subjects lacking those files (i.e.
`segmentHA_T1.sh` never ran) are reported and skipped from those two files only.

## suvr_stats_all.py

```bash
python3 suvr_stats_all.py -rd /path/to/ADRC -o suvr_output              # all four
python3 suvr_stats_all.py -rd /path/to/ADRC -o suvr_output \
        --pattern suvr_combined_cerebellum                              # just one
```

Finds every `res/` folder, picks the CSV ending in `_<pattern>.csv`, and stacks the rows. Pure
pandas — no FreeSurfer needed.

| `--pattern` | Reference | Format |
|---|---|---|
| `suvr_combined_cerebellum_gm` *(default)* | cerebellar GM | summary: `PID, Compound, Centiloid` + ~22 ROI groups |
| `suvr_combined_cerebellum` | whole cerebellum | same |
| `suvr_cerebellum_gm` | cerebellar GM | per-region: `PID` + ~116 FreeSurfer regions |
| `suvr_cerebellum` | whole cerebellum | same |

Pattern matching is anchored to the trailing token, so `suvr_cerebellum` does not also match
`suvr_cerebellum_gm`.

Two file layouts are handled automatically: combined summaries are one header + one data row;
per-region files carry a **two-row header** (line 1 = FreeSurfer label numbers, line 2 = region
names) and the reader uses the names, dropping the number row.

Pair identifiers are parsed from the combo folder name by splitting on `_pet_` / `_mri_`:

| Folder name | subject_id | pet_date | pet_info | mri_date | mri_info |
|---|---|---|---|---|---|
| `110001_pet_20200310_mri_20200115` | 110001 | 20200310 | — | 20200115 | — |
| `110001_pet_20200310_128_mri_20200115` | 110001 | 20200310 | 128 | 20200115 | — |
| `110002_pet_20200310_mri_20200115_CorMPRAGE` | 110002 | 20200310 | — | 20200115 | CorMPRAGE |

Output columns: `subject_id, pet_date, pet_info, mri_date, mri_info`, then the original
`PID, Compound, Centiloid, <ROI SUVRs...>`.

`res/` folders with no matching CSV are skipped and reported — worth reading, since malformed PET
session names show up here.

## mri_site_data.py

```bash
python3 mri_site_data.py /path/to/ADRC --cores 4 [--force]
```

Builds the shareable derivative of each recon: `mri/{T1,brain,wm,aparc+aseg}.mgz` → NIfTI and
`surf/{lh,rh}.{pial,white}` → GIFTI, written to each session's `sitedata_mri/`. Uses `mri_convert`
and `mris_convert`. Logs to `<path>/conversion_logs/`.

Regenerable at any time from the recon, so it is the first thing to delete if space is tight.

## anat_report.py

```bash
python3 anat_report.py /path/to/ADRC -o mri_scans.csv
```

Inventory of every `anat/` file with parsed `SubjID, Scandate, Modality, Filepath`. The quickest way
to verify an ingest before committing CPU-days to `recon-all`.

## pet_report.py

```bash
python3 pet_report.py /path/to/ADRC -o pet_folders.csv
```

Lists every `pet/` directory and its files. Stdlib only.

## ConcatenateSubregionsResults

Vendored FreeSurfer utility (internally `quantifyData.sh`). Concatenates a named `.stats` file across
all subjects in a `SUBJECTS_DIR`:

```bash
./ConcatenateSubregionsResults -f hipposubfields.lh.T1.v22.stats -o outdir -s /path/to/SUBJECTS_DIR
```

Rarely needed — `mri_stats_all.py` covers the standard tables.
