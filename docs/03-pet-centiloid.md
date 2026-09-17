# 3. Processing PET with MRI — SUVR and Centiloid

Quantifies amyloid PET against each subject's own FreeSurfer segmentation, producing regional SUVRs
and a Centiloid score.

**Prerequisite: the subject's MRI must already be through `recon-all`**
([02-mri-processing.md](02-mri-processing.md)). There is no PET-only path — the anatomy defines both
the target regions and the reference region.

```
PET + recon-all output
   → prepare_suvr_folder.py   build pair folders, convert volumes, export stats
   → registration.py          FSL FLIRT, PET into T1 space
   → suvr.py                  per-ROI SUV → SUVR → Centiloid
```

---

## The approach in one paragraph

PET is registered into the subject's FreeSurfer **conformed T1 space** (256³, 1 mm isotropic). The
`aparc+aseg` segmentation is resampled onto the same grid, so PET voxels and anatomical labels line
up index-for-index and regional values can be read out directly in NumPy — no `mri_segstats`, no
atlas warping, no group template. Cortical uptake is normalized to the cerebellum, and the resulting
composite SUVR is converted to Centiloid with a tracer-specific linear equation.

---

## Ingest PET

Same shape as the MRI ingest, with the PET converter:

```bash
python3 pipeline/1_ingest/download.py links.csv --type PET --output-dir /path/to/batch
python3 pipeline/1_ingest/prefix.py /path/to/batch/PET --prefix PET_        # if needed
python3 pipeline/1_ingest/dropbox_pet_to_bids.py /path/to/batch/PET --target_dir /path/to/batch
```

Produces:

```
<target>/ADRC/<subjid>/<YYYYMMDD>/
├── pet/  <subjid>-<YYYYMMDD>_PET.nii
└── ct/   <subjid>-<YYYYMMDD>_CT.nii      (only when the delivery includes CT)
```

PET series are identified by substrings in the delivered filenames — `mean_5mmblur`, `PET_6mmblur`,
`PET_3mmblur`, `PET_256` — and CT by `amyloid_pet_ct` or `pet_ct`. **These patterns are
scanner- and site-specific.** If your reconstructions are named differently, edit the pattern lists
in [`dropbox_pet_to_bids.py`](../pipeline/1_ingest/dropbox_pet_to_bids.py) (around lines 140 and 159)
before running.

Unlike the MRI converter, the session token in the folder name is **mandatory** here:
`PET_<subjid>-<session>_<MMDDYYYY>`.

---

## Step 1 — Build the pair folders

```bash
python3 pipeline/3_suvr/prepare_suvr_folder.py /path/to/batch/ADRC --cores 8
```

| Flag | Meaning |
|---|---|
| `--cores N` | Worker processes |
| `--parallel-mode subjects\|combinations` | Parallelize over subjects (default) or over PET–MRI pairs |
| `--disable-parallel` | Serial, for debugging |
| `--single-subject <id>` | One subject only |
| `-v` | Verbose |

### Every PET is paired with every MRI

This is the single most important thing to understand about this stage. For each subject the script
builds the **full cross-product** of PET scans × MRI sessions — not a nearest-date match. A subject
with 4 PET scans and 5 MRI sessions produces **20** pair folders.

That is deliberate: it lets you choose the pairing afterwards (nearest-in-time, baseline MRI, or a
longitudinal series) without reprocessing. It is also why this tree gets large — roughly 150 MB per
pair. If you only want specific pairings, run with `--single-subject` and prune, or filter at the
aggregation step.

### Output structure

```
ADRC/<subjid>/<PETdate>/suvr/
└── <subjid>-<PETdate>_PET/
    ├── logs/
    └── <subjid>_pet_<PETdate>_mri_<MRIdate>/
        ├── MRI/            inputs for this pair
        ├── register_scan/  filled by step 2
        └── res/            filled by step 3
```

Note the SUVR tree lives under the **PET** session, keyed by MRI date.

### What lands in `MRI/`

| File | Produced by |
|---|---|
| `<mri>.nii` | `mri_convert -ot nii --out_orientation RAS` on `T1.mgz` |
| `<mri>_aparc+aseg.nii` | same conversion on `aparc+aseg.mgz` |
| `<pet>.nii` | the raw PET, copied in |
| `<mri>_asegVolume.csv` | `asegstats2table -m volume` |
| `<mri>_aparcstatsVolumLeft.csv` | `aparcstats2table --hemi lh --meas volume` |
| `<mri>_aparcstatsVolumRight.csv` | `aparcstats2table --hemi rh --meas volume` |

Both volumes are converted with the **same** `--out_orientation RAS`, which is what guarantees PET
and segmentation share a grid. The three CSVs are not incidental — the SUVR step uses those volumes
as weights, so it needs anatomical volumes independent of the PET.

---

## Step 2 — Register PET to MRI

```bash
python3 pipeline/3_suvr/registration.py /path/to/batch/ADRC --cores 8
```

Runs FSL FLIRT per pair, PET as input, the converted T1 as reference:

```bash
flirt -in <PET> -ref <T1> -out <output>.nii -omat <output>.mat \
      -bins 256 -cost corratio \
      -searchrx -90 90 -searchry -90 90 -searchrz -90 90 \
      -dof 12 -interp trilinear
```

Output goes to `register_scan/` as
`<subjid>-<PETdate>_reg_<subjid>-<MRIdate>_<modality>.nii` plus the `.mat` transform. Existing
outputs are skipped, so the step is resumable.

> **Note on 12 DOF.** This is a full affine registration. Within-subject PET→MRI is conventionally
> done with 6 DOF (rigid), since the same head in two scanners differs only by pose. The extra six
> parameters let FLIRT absorb scanner scaling differences, but they can also absorb real signal.
> This matches the historical implementation these results were validated against; if you are
> starting fresh, consider `-dof 6`.

Check a few registrations visually before trusting a batch — `fsleyes` overlaying
`register_scan/*.nii` on `MRI/<mri>.nii` is the quickest way.

---

## Step 3 — SUVR and Centiloid

```bash
python3 pipeline/3_suvr/suvr.py /path/to/batch/ADRC
```

| Flag | Meaning |
|---|---|
| `--compound neuraceq\|amyvid` | Force the tracer instead of inferring it from the scan date |
| `--single-subject <id>` | One subject only |
| `-v` | Verbose |

Pure Python — `nibabel`, `numpy`, `pandas`. No FreeSurfer or FSL needed at this step.

### 3a. Per-ROI uptake

The registered PET and the resampled `aparc+aseg` are loaded, voxels where the label is 0 are
dropped, and for each label the mean, median, and sum of PET intensity are computed, along with a
global min and max. Label names come from
[`FreesurferLUTR.txt`](../pipeline/3_suvr/FreesurferLUTR.txt) — 116 rows of `ROI,Name` covering the
aseg subcortical labels and the Desikan–Killiany cortical parcellation. **This file must sit beside
`suvr.py`**; it is loaded from `Path(__file__).parent`.

### 3b. Reference region

Two references are computed, both as **volume-weighted** means of per-ROI mean uptake, using the
volumes from `<mri>_asegVolume.csv`:

| Reference | aseg labels | Regions | Used by |
|---|---|---|---|
| **Whole cerebellum** (primary) | **7, 8, 46, 47** | L/R cerebellar white matter + L/R cerebellar cortex | `*_suvr_cerebellum.csv`, `*_suvr_combined_cerebellum.csv` |
| **Cerebellar gray matter** | **8, 47** | L/R cerebellar cortex only | the `*_gm` variants |

`SUVR = ROI mean uptake / reference`.

### 3c. Target regions

Five bilateral cortical regions, each pooled volume-weighted across its labels and hemispheres:

| Region | Left labels | Desikan–Killiany parcels |
|---|---|---|
| **AnteriorCingulate** | 1026, 1002 | rostral + caudal anterior cingulate |
| **PosteriorCingulate** | 1023, 1010 | posterior cingulate, isthmus cingulate |
| **Frontal** | 1003, 1012, 1014, 1018, 1019, 1020, 1027, 1028, 1032 | caudal middle frontal, lateral orbitofrontal, medial orbitofrontal, pars opercularis, pars orbitalis, pars triangularis, rostral middle frontal, superior frontal, frontal pole |
| **Temporal** | 1030, 1015 | superior temporal, middle temporal |
| **Parietal** | 1008, 1025, 1029, 1031 | inferior parietal, precuneus, superior parietal, supramarginal |

Right-hemisphere labels are the same values plus 1000 (e.g. 2026, 2002).

Two composites are derived:

- **Global** — volume-weighted pool of those five regions. **This is the value that drives Centiloid.**
- **Total** — volume-weighted pool of *all* cortical labels (1001–1035, 2001–2035).

Pooling is volume-weighted throughout —
`(Σ SUVR_i × vol_i) / Σ vol_i`, not an average of hemisphere averages. This was changed deliberately
to match the original R implementation these results were validated against.

> ### Results produced before this change differ
>
> An earlier version of `suvr.py` combined hemispheres with a plain `(Left + Right) / 2` and averaged
> ROI SUVRs unweighted. Re-running the current code over a pair folder processed under the old
> version reproduces the **per-hemisphere** values exactly but gives different **bilateral combined**
> and **Total** values:
>
> | Value | Old (unweighted) | Current (volume-weighted) |
> |---|---|---|
> | `GlobalLeft`, `GlobalRight` | — | identical to 15 decimal places |
> | `Global` | 1.1458546 | 1.1458527 |
> | `Centiloid` | 32.5116 | 32.5113 |
> | `AnteriorCingulate` | 1.1869851 | 1.1919999 |
> | `Total` | 1.1423640 | 1.1213082 |
>
> **Centiloid is barely affected** (~0.0003 CL) because `Global` is dominated by the per-hemisphere
> values, which are unchanged. The bilateral regional SUVRs and `Total` shift by up to ~2%.
>
> If your dataset was processed over a long period, it may contain a mixture. Check by recomputing
> `(Left + Right) / 2` from a stored row: if it equals the stored combined value, that row came from
> the old code. Re-run `suvr.py` on affected pairs to bring them onto the current method — nothing
> upstream needs redoing, since step 3 reads only the registered PET and the stats CSVs.

### 3d. Centiloid conversion

```
Amyvid   (¹⁸F-florbetapir):  CL = 183.07 × SUVR_global − 177.26
Neuraceq (¹⁸F-florbetaben):  CL = 153.4  × SUVR_global − 154.9
```

Computed against both references, so you get a whole-cerebellum and a GM-referenced Centiloid.

**Tracer assignment** is by scan date: **on or after 2016-09-27 → Neuraceq, before → Amyvid.** That
is the date our sites switched tracers. Override with `--compound`.

> ### ⚠️ Tracer exceptions are not implemented
>
> Our records document a small number of subjects who received the *other* tracer than their scan
> date implies. `determine_compound()` applies only the date rule, so those subjects get the wrong
> Centiloid equation — the SUVRs are unaffected, but the Centiloid values are wrong.
>
> **If you have such exceptions, run them separately with an explicit `--compound`:**
> ```bash
> python3 pipeline/3_suvr/suvr.py /path/to/ADRC --single-subject 900001 --compound amyvid
> ```
> Maintaining a tracer lookup table keyed by subject and PET date, rather than relying on the
> cutoff date, is the durable fix.
>
> **If you are adapting this pipeline to another cohort, the 2016-09-27 date is meaningless to you.**
> Change it or always pass `--compound`.

### Outputs — `res/`

With `<combo>` = `<subjid>_pet_<PETdate>_mri_<MRIdate>`:

| File | Contents |
|---|---|
| `<combo>_mean_suv.csv` | per-ROI mean uptake |
| `<combo>_median_suv.csv` | per-ROI median uptake |
| `<combo>_total_suv.csv` | per-ROI summed uptake |
| `<combo>_suvr_cerebellum.csv` | per-ROI SUVR, whole-cerebellum reference |
| `<combo>_suvr_cerebellum_gm.csv` | per-ROI SUVR, GM reference |
| `<combo>_suvr_combined_cerebellum.csv` | **headline result** — PID, Compound, Centiloid, 21 regional SUVRs |
| `<combo>_suvr_combined_cerebellum_gm.csv` | same, GM reference |
| `<combo>_max`, `_min`, `_suv_cer`, `_suv_cer_gm` | scalars, no extension |

The combined CSV is the one to read:

```
PID,Compound,Centiloid,AnteriorCingulateLeft,...,GlobalLeft,GlobalRight,Global
900001-20200310_reg_900001-20200115_T1w.nii,Neuraceq,-8.395,0.957,...,0.955
```

---

## Step 4 — Aggregate across the study

```bash
# keep only the MRI registration closest to each PET (dry run first, then --execute)
python3 pipeline/5_aggregate/prune_suvr_registrations.py --source /path/to/ADRC
python3 pipeline/5_aggregate/prune_suvr_registrations.py --source /path/to/ADRC \
        --execute --quarantine /path/to/NWSI/suvr_pruned

python3 pipeline/5_aggregate/suvr_symlink.py --source /path/to/ADRC --target /path/to/NWSI/suvr_link
python3 pipeline/5_aggregate/suvr_stats_all.py -ld /path/to/NWSI/suvr_link -o suvr_output
```

Pruning comes first because every registration of a PET scan becomes its own row in the tables. If
you want all PET×MRI combinations, skip it.

`suvr_stats_all.py` walks every `res/` directory reachable from the flat SUVR symlink farm and concatenates the four
SUVR CSV families into study-level tables, parsing subject, PET date, and MRI date out of each pair
folder name. See [`pipeline/5_aggregate/README.md`](../pipeline/5_aggregate/README.md).

---

## Known limitations

| | |
|---|---|
| **Tracer exceptions** | Not implemented — date rule only. See the warning above. |
| **Only two tracers** | Florbetapir and florbetaben. PiB, flutemetamol, and NAV4694 need their own Centiloid coefficients added to `calculate_centiloid()`. |
| **`Total` includes corpus callosum** | Labels 1004/2004 (`ctx-?h-corpuscallosum`) are in the all-cortical pool. Affects `Total` only — **not** `Global`, and therefore not Centiloid. |
| **12-DOF registration** | See the note in step 2. |
| **No partial-volume correction** | Uptake is read from the registered PET as-is. Expect the usual PVE-driven underestimation in thin cortex. |
| **Fallback path in `suvr.py` is broken** | Around line 586 a `register_scan` fallback assigns a generator and then calls `.glob()` on it, raising `AttributeError`. Only reachable if the directory layout differs from what step 1 produces; the normal path is unaffected. |
| **`freesurfer741` is hardcoded** | The recon directory name is a string literal in `prepare_suvr_folder.py`. |

---

## Next

- **Merge results into the main dataset** → [04-data-organization.md](04-data-organization.md)
- **Something failed** → [05-troubleshooting.md](05-troubleshooting.md)
