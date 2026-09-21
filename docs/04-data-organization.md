# 4. Organizing the data

The layout every script in this repository reads and writes. Get this right and the pipeline works;
get it wrong and scripts silently find nothing.

> **This is not BIDS.** Despite some script names, there are no `sub-`/`ses-` prefixes, no
> `dataset_description.json`, no `participants.tsv`, and derivatives nest inside sessions rather than
> under a `derivatives/` root. It is a custom subject/date/modality layout. If you need real BIDS,
> you will need a conversion layer.

---

## The shape

```
ADRC/
├── 900001/                                  ← subject: bare 6-digit ID
│   │
│   ├── 20200115/                            ← MRI session: bare YYYYMMDD
│   │   ├── anat/
│   │   │   └── 900001-20200115_T1w.nii
│   │   ├── modalities/                      ← raw delivery, preserved verbatim
│   │   │   ├── 900001-05_01152020.Cor_MPRAGE.nii
│   │   │   ├── 900001-05_01152020.DTI1000.nii  + .bval + .bvec
│   │   │   ├── 900001-05_01152020.T2FLAIR.nii
│   │   │   └── *.json                       ← scanner sidecars, original names
│   │   ├── freesurfer741/
│   │   │   └── 900001-20200115_T1w/         ← a complete recon-all subject
│   │   │       ├── mri/    T1.mgz, aparc+aseg.mgz, hippoAmygLabels-T1.v22.*
│   │   │       ├── surf/   lh.pial, rh.white, ...
│   │   │       ├── label/
│   │   │       ├── stats/  aseg.stats, ?h.aparc.stats,
│   │   │       │           hipposubfields.?h.T1.v22.stats,
│   │   │       │           amygdalar-nuclei.?h.T1.v22.stats
│   │   │       └── scripts/ recon-all.log [, recon-all.error]
│   │   └── sitedata_mri/                    ← shareable derivative
│   │       ├── mri/   T1.nii, brain.nii, wm.nii, aparc+aseg.nii
│   │       └── surf/  lh.pial.gii, rh.white.gii, ...
│   │
│   ├── 20200310/                            ← PET session: its own date folder
│   │   ├── pet/
│   │   │   └── 900001-20200310_PET.nii
│   │   ├── ct/                              ← only when the delivery includes CT
│   │   │   └── 900001-20200310_CT.nii
│   │   └── suvr/
│   │       ├── logs/suvr_setup_20200310_<ts>.log
│   │       └── 900001-20200310_PET/
│   │           ├── logs/pet_registration_<ts>.log
│   │           └── 900001_pet_20200310_mri_20200115/
│   │               ├── MRI/            T1, aparc+aseg, PET, 3 volume CSVs
│   │               ├── register_scan/  *_reg_*.nii + .mat
│   │               └── res/            SUVR + Centiloid CSVs
│   │
│   └── logs/
│       └── pet_suvr_processing_900001_<ts>.log
│
├── 900002/
├── ...
└── logs/                                    ← batch-level, siblings of the subjects
    ├── mri_bids_logs/    pet_bids_logs/
    ├── mri_rsync_log/    pet_rsync_log/
    ├── fs_logs/          conversion_logs/
    └── modality/
```

---

## Rules

**1. Subjects are bare IDs.** Six digits, no prefix. The first three digits are the site code
(`110`, `120`, `220`, `320`). Every example in this repo uses a `9xxxxx` ID, a range no real
subject uses.

**2. Sessions are bare dates.** `YYYYMMDD`. No time component, no `ses-`. Each subject has exactly
one non-date child: `logs/`.

**3. A session is either MRI or PET, never both.** MRI sessions hold `anat/`, `freesurfer741/`,
`sitedata_mri/`. PET sessions hold `pet/`, optionally `ct/`, and `suvr/`. This falls out of
acquisition — the two modalities are scanned on different days, so each gets its own date folder.

**4. Filenames are `<subjid>-<YYYYMMDD>_<SUFFIX>.nii`.** Hyphen between ID and date, underscore
before the suffix. This is parsed by nearly every script; deviations are silently skipped.

| Suffix | Where | Notes |
|---|---|---|
| `_T1w` | `anat/` | Preferred structural scan |
| `_CorMPRAGE` | `anat/` | Fallback when no T1 series exists |
| `_PET` | `pet/` | |
| `_CT` | `ct/` | |

**5. Everything is uncompressed `.nii`.** There is not a single `.nii.gz` in the tree. FreeSurfer
handles both, but the filename patterns the scripts match on assume `.nii`.

**6. PET reconstruction variants become filename suffixes** — `_PET_128`, `_PET_256`, `_PET_a`,
`_PET_BIG` — and those suffixes then propagate into the SUVR directory names downstream.

**7. Raw delivery is never discarded.** `modalities/` keeps every file from the vendor, including
DTI, FLAIR, SWI, resting-state, and their original JSON/bval/bvec sidecars. Note the JSONs keep
scanner series descriptions rather than matching the NIfTI names, so they are *not* usable as BIDS
sidecars.

**8. The FreeSurfer subject ID is the anat filename stem.** `900001-20200115_T1w` — subject and date
embedded, hence globally unique. There is **no central `SUBJECTS_DIR`**; recons are scattered one per
session. `pipeline/5_aggregate/freesurfer_symlink.py` builds a persistent flat symlink farm precisely to
work around this — one symlink per recon, pointing back at the real nested directory — which
`pipeline/5_aggregate/mri_stats_all.py` then points FreeSurfer's table tools at directly. The same
pattern applies to SUVR output via `pipeline/5_aggregate/suvr_symlink.py`.

**9. SUVR is a PET × MRI cross-product.** One pair folder per combination, named
`<subjid>_pet_<PETdate>_mri_<MRIdate>`. Note the pair folders use underscores throughout, unlike the
hyphen-then-underscore file convention. This fan-out is the largest driver of tree size.

**10. Merges are append-only.** All assembly uses `rsync -av --copy-links --ignore-existing`, so
re-running a batch never overwrites anything already present. `--copy-links` dereferences symlinks so
the destination is self-contained.

---

## Building the tree

### From a raw delivery

Batches are processed in a staging area, then merged in:

```
Processing/Both/batch12/ADRC/   ← ingest + recon-all + SUVR happen here
            ↓  rsync
NWSI/ADRC/                      ← the assembled dataset
```

Steps 1–3 are covered in [02-mri-processing.md](02-mri-processing.md) and
[03-pet-centiloid.md](03-pet-centiloid.md). The merge:

```bash
export PROCESSING_ROOT=/data/Processing
export ADRC_ROOT=/data/NWSI/ADRC

./sync/sync_batch.sh 12            # MRI + PET batch
./sync/mri_sync_batch.sh 12        # MRI-only batch
./sync/pet_sync_batch.sh 12        # PET-only batch
```

Each writes a log under `${ADRC_ROOT}/logs/{mri,pet}_rsync_log/batch12.log`. Watch it:

```bash
tail -f /data/NWSI/ADRC/logs/mri_rsync_log/batch12.log
```

To publish the assembled dataset onward to a network share:

```bash
SHARE_ROOT=/mnt/share/SiteData/ADRC ./sync/rsync_adrc_sync.sh
```

> Writing to a shared mount may need elevated permissions. These scripts do **not** call `sudo` —
> run them under an account that can write to the destination, or prefix with `sudo` yourself.

### Generating `sitedata_mri/`

The `freesurfer741/` recon is ~294 MB of FreeSurfer-native `.mgz` and binary surfaces — awkward to
share. `sitedata_mri/` is a portable derivative in standard formats:

```bash
python3 pipeline/5_aggregate/mri_site_data.py /path/to/ADRC --cores 4
```

Converts `mri/{T1,brain,wm,aparc+aseg}.mgz` → NIfTI and `surf/{lh,rh}.{pial,white}` → GIFTI, writing
into each session's `sitedata_mri/`. Use `--force` to regenerate.

To see which scans are already converted before starting a long run:

```bash
python3 pipeline/5_aggregate/mri_site_data.py /path/to/ADRC --status
```

This changes nothing and needs no FreeSurfer. It reports each scan as `complete`, `stale`,
`partial`, `not_started` or `no_source`, and ends with the exact number of files a rerun would
convert. `stale` means recon-all ran again after the conversion, so the derivative no longer matches
its recon — a plain rerun reconverts those files. See `pipeline/5_aggregate/README.md`.

### Study-level tables

Two scripts collapse the whole tree into flat CSVs, written outside `ADRC/`. Both read from flat
symlink farms rather than walking `ADRC/` directly, so build/refresh those first (idempotent — safe
to rerun any time, only adds symlinks for new subjects/scans):

```bash
python3 pipeline/5_aggregate/freesurfer_symlink.py --source /path/to/ADRC --target /path/to/NWSI/freesurfer_link
python3 pipeline/5_aggregate/suvr_symlink.py       --source /path/to/ADRC --target /path/to/NWSI/suvr_link

python3 pipeline/5_aggregate/mri_stats_all.py  -ld /path/to/NWSI/freesurfer_link -o mri_output
python3 pipeline/5_aggregate/suvr_stats_all.py -ld /path/to/NWSI/suvr_link       -o suvr_output

# progress check: folders in ADRC/ against entries in the two farms
python3 pipeline/7_DirectoryStats/directory_data_count.py -i /path/to/NWSI
```

```
NWSI/
├── ADRC/             the subject tree
├── freesurfer_link/  symlink farm, one link per recon
├── suvr_link/        symlink farm, one link per PET output folder
├── suvr_pruned/      registrations moved aside by prune_suvr_registrations.py --quarantine
├── mri_output/       aseg_stats.csv, aparc_volume.csv, aparc_thickness.csv,
│                     wmparc.csv, hippocampus.csv, amygdala.csv
└── suvr_output/      suvr_cerebellum.csv, suvr_cerebellum_gm.csv,
                      suvr_combined_cerebellum.csv, suvr_combined_cerebellum_gm.csv
```

The two farms and the output tables are the only index artifacts. There is no manifest or participants file inside `ADRC/` itself —
the directory structure *is* the index.

---

## Finding and viewing scans

To find and inspect specific scans by subject ID and date, use
[`pipeline/6_extract/`](../pipeline/6_extract/):

```bash
export ADRC_ROOT=/data/NWSI/ADRC

# browse and view any volume in a browser (over SSH: ssh -L 8765:localhost:8765 you@server)
python3 pipeline/6_extract/viewer.py

# what sessions exist for a subject, and which scans are in each?
python3 pipeline/6_extract/scans.py 900001

# one scan's path
python3 pipeline/6_extract/scans.py 900001 01/15/2020 -t t1w
```

Dates may be `MM/DD/YYYY`, `YYYY-MM-DD` or `YYYYMMDD`.

---

## Logs

Four nested tiers, all timestamped `YYYYMMDD_HHMMSS`:

| Tier | Location | Written by |
|---|---|---|
| Batch | `ADRC/logs/<category>/batchNN.log` | ingest, rsync |
| Subject | `ADRC/<subj>/logs/pet_suvr_processing_*.log` | SUVR driver |
| Session | `ADRC/<subj>/<date>/suvr/logs/suvr_setup_*.log` | `prepare_suvr_folder.py` |
| Pair | `.../suvr/<PETdir>/logs/pet_registration_*.log` | `registration.py` |

Many are zero bytes. That is normal — a log is opened per run whether or not anything is written.

---

## Storage planning

| Item | Size |
|---|---|
| One `anat/` T1 | ~16 MB |
| One `ct/` volume | ~129 MB |
| One `freesurfer741/` recon | **~294 MB** |
| One `sitedata_mri/` | ~130 MB |
| One SUVR pair folder | **~150 MB** (67 MB aparc+aseg + 67 MB registered PET + 16 MB T1) |
| Subject with 3 MRI + 1 PET (3 pairs) | ~1.7 GB |
| Subject with 5 MRI + 4 PET (~20 pairs) | ~4.7 GB |

A 780-subject cohort with ~856 recons and ~2,800 pair folders runs to roughly **0.8–1.2 TB**.

The two multipliers to watch are the PET × MRI cross-product and `sitedata_mri/` duplicating data
already in `freesurfer741/`. If space is tight, `sitedata_mri/` is regenerable from the recon at any
time, and pair folders for unwanted pairings can be deleted without affecting the rest.

---

## Migrating to a newer FreeSurfer

To copy the tree while leaving derived outputs behind — e.g. re-running under FreeSurfer 8:

```bash
rsync -av --exclude='*/freesurfer741/' --exclude='*/suvr/' --exclude='*/sitedata_mri/' \
      /source/ADRC/ /destination/ADRC/
```

This keeps `anat/`, `pet/`, `ct/`, and `modalities/` — everything that is source data — and drops
everything reproducible.
