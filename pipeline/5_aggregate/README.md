# 5. Aggregation and reporting

Walks the assembled dataset and collapses it into flat, study-level CSVs. Also includes utilities
for pruning SUVR registrations, building symlink farms, generating shareable derivatives, and
counting what has been processed.

Typical order after a batch is synced: `prune_suvr_registrations.py` → `freesurfer_symlink.py` +
`suvr_symlink.py` → `mri_stats_all.py` + `suvr_stats_all.py` → `directory_data_count.py`.

| Script | Output | Row = | Needs |
|---|---|---|---|
| `prune_suvr_registrations.py` | removes (or quarantines) extra MRI registrations per PET | — | stdlib |
| `freesurfer_symlink.py` | flat FreeSurfer symlink farm | one recon | stdlib |
| `suvr_symlink.py` | flat SUVR symlink farm | one PET output folder | stdlib |
| `mri_stats_all.py` | 6 per-measure CSVs | one recon MRI subject | FreeSurfer on PATH, FreeSurfer symlink farm |
| `suvr_stats_all.py` | one CSV per pattern (4 total) | one PET–MRI pair | pandas only, SUVR symlink farm |
| `mri_site_data.py` | `sitedata_mri/` per session | — | FreeSurfer on PATH |
| `directory_data_count.py` | printed counts of `anat`/`ct`/`pet`/`modalities` folders and farm entries | — | stdlib |
| `ConcatenateSubregionsResults` | concatenated `.stats` across subjects | one subject | FreeSurfer (vendored utility) |

Expected input layout: [docs/04-data-organization.md](../../docs/04-data-organization.md).

`mri_stats_all.py` and `suvr_stats_all.py` read from flat symlink farms rather than walking the
nested `ADRC/` tree directly (recons and SUVR output are scattered one per session, with no central
`SUBJECTS_DIR`). Build/refresh the farms first:

```bash
python3 freesurfer_symlink.py --source /path/to/ADRC --target /path/to/NWSI/freesurfer_link
python3 suvr_symlink.py       --source /path/to/ADRC --target /path/to/NWSI/suvr_link
```

Both are safe to rerun any time (idempotent — only adds symlinks for new subjects/scans). See
[freesurfer_symlink.py](#freesurfer_symlinkpy-and-suvr_symlinkpy) below.

---

## prune_suvr_registrations.py

```bash
python3 prune_suvr_registrations.py --source /path/to/ADRC                     # dry run
python3 prune_suvr_registrations.py --source /path/to/ADRC --execute \
        --quarantine /path/to/NWSI/suvr_pruned                                 # move extras aside
python3 prune_suvr_registrations.py --source /path/to/ADRC --execute           # delete extras
```

A PET output folder under `suvr/` can hold one registration per FreeSurfer MRI session. This script
keeps the registration whose MRI date is closest to the PET session date and removes the others. Run
it before `suvr_stats_all.py`, or every registration of the same PET ends up as its own row.

- The PET date comes from the `<session>` folder name. The MRI date is the token after `_mri_`.
- Ties and unparseable dates are skipped and reported as `SKIP`. They are never removed.
- It is a **dry run unless `--execute` is given**. With `--quarantine DIR`, removed folders are moved
  under `DIR` with their ADRC-relative path, so they can be restored.

| Option | Default | |
|---|---|---|
| `--source` | required | ADRC root |
| `--dirname` | `suvr` | session-level SUVR folder name |
| `--execute` | off | actually remove or move folders |
| `--quarantine DIR` | — | move instead of delete |

## freesurfer_symlink.py and suvr_symlink.py

```bash
python3 freesurfer_symlink.py --source /path/to/ADRC --target /path/to/NWSI/freesurfer_link [--dry-run] [--force]
python3 suvr_symlink.py       --source /path/to/ADRC --target /path/to/NWSI/suvr_link       [--dry-run] [--force]
```

Each script creates one symlink per output folder in a single flat directory. No data is moved or
copied.

| Script | Links to | Excluded | Folder option |
|---|---|---|---|
| `freesurfer_symlink.py` | `<subj>/<date>/freesurfer741/<subj>-<date>_<seq>` | `fsaverage` | `--fs-dirname` (default `freesurfer741`, exact match, so `freesurfer741_t` is skipped) |
| `suvr_symlink.py` | `<subj>/<date>/suvr/<subj>-<date>_PET[...]` | `logs` | `--dirname` (default `suvr`) |

Every `_PET_128`, `_PET_256`, `_PET_a` variant gets its own link. An existing link that points
somewhere else is left alone unless you pass `--force`. A real file or folder with the same name is
never overwritten. The run ends with a summary of links created, replaced, already up to date, and
skipped.

## directory_data_count.py

```bash
python3 directory_data_count.py -i /path/to/NWSI
```

`-i` is the NWSI root: the folder that contains `ADRC/`, `freesurfer_link/` and `suvr_link/`.
Without `-i` it uses the `NWSI_ROOT` environment variable, and exits with an error if neither is set.

```
Subjects in ADRC: 780

== ADRC folders (ADRC/<subject>/<date>/<folder>) ==
  anat            857
  ct               57
  pet             606
  modalities      414

== Processed outputs ==
  freesurfer_link     856  (broken links: 0)
  suvr_link           574  (broken links: 0)
```

`anat` against `freesurfer_link` shows how many T1s still need `recon-all`. `pet` against
`suvr_link` shows how many PET scans still need SUVR. A broken link means the output folder it
pointed to was moved or deleted. Rebuild the farm with `--force` or remove the link.

---

## mri_stats_all.py

```bash
source $FREESURFER_HOME/SetUpFreeSurfer.sh
python3 mri_stats_all.py -fd /path/to/NWSI/freesurfer_link -o mri_output
```

1. Lists every entry in the flat FreeSurfer symlink farm (skipping any without a `stats/` dir) —
   the farm is a flat directory of symlinks, one per `<subjid>-<scandate>_<type>` recon, built by
   `freesurfer_symlink.py`.
2. Points `SUBJECTS_DIR` straight at the farm so FreeSurfer's table tools see one flat subjects
   directory — necessary because recons are scattered one per session with no central `SUBJECTS_DIR`
   on disk.
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
python3 suvr_stats_all.py -sd /path/to/NWSI/suvr_link -o suvr_output         # all four
python3 suvr_stats_all.py -sd /path/to/NWSI/suvr_link -o suvr_output \
        --pattern suvr_combined_cerebellum                                   # just one
```

Walks the flat SUVR symlink farm (`suvr_symlink.py` — one symlink per PET
scan), finds every `res/` folder reachable from each entry, picks the CSV ending in
`_<pattern>.csv`, and stacks the rows. Pure pandas — no FreeSurfer needed.

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

## ConcatenateSubregionsResults

Vendored FreeSurfer utility (internally `quantifyData.sh`). Concatenates a named `.stats` file across
all subjects in a `SUBJECTS_DIR`:

```bash
./ConcatenateSubregionsResults -f hipposubfields.lh.T1.v22.stats -o outdir -s /path/to/SUBJECTS_DIR
```

Rarely needed — `mri_stats_all.py` covers the standard tables.
