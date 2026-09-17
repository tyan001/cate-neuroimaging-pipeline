# CATE Neuroimaging Pipeline

End-to-end processing for Alzheimer's disease neuroimaging: structural MRI through FreeSurfer 7, and
amyloid PET quantified against each subject's own segmentation to produce SUVR and **Centiloid**
scores.

Built for the CATE study at Florida International University and the NWSI multi-site initiative.
No subject data is included in this repository.

---

## What it does

```
   raw delivery (NIfTI + Dropbox links)
        │
   ┌────▼─────────┐
   │  1. ingest   │  download, unzip, organize into subject/date/modality
   └────┬─────────┘
        │
   ┌────▼─────────┐
   │ 2. freesurfer│  recon-all  +  segmentHA_T1.sh          [8–12 h per scan]
   └────┬─────────┘
        │
   ┌────▼─────────┐
   │   4. qc      │  find failed recons, missing segmentations
   └────┬─────────┘
        │
   ┌────▼─────────┐
   │  3. suvr     │  pair PET×MRI → FLIRT registration → SUVR → Centiloid
   └────┬─────────┘
        │
   ┌────▼─────────┐   ┌──────────┐
   │ 5. aggregate │   │  sync    │  merge batches into the dataset (append-only)
   │              │   └──────────┘
   │  study-level CSVs: aseg, aparc, hippocampus, amygdala, SUVR
   └────┬─────────┘
        │
   ┌────▼─────────┐
   │  6. extract  │  pull specific scans back out by subject + date
   └──────────────┘
```

---

## Guides

Read these in order the first time.

| | Guide |
|---|---|
| **1** | [Building the FreeSurfer 7 environment](docs/01-environment.md) — Docker image, license, container launch |
| **2** | [Processing MRI scans](docs/02-mri-processing.md) — ingest through `recon-all` and QC |
| **3** | [Processing PET with MRI → Centiloid](docs/03-pet-centiloid.md) — registration, SUVR, Centiloid |
| **4** | [Organizing the data](docs/04-data-organization.md) — the directory layout everything assumes |
| **5** | [Troubleshooting](docs/05-troubleshooting.md) — failure modes and known limitations |

---

## Quickstart

```bash
git clone <this-repo> && cd cate-neuroimaging-pipeline

# 1. Build the environment (~30–60 min; needs a FreeSurfer license)
docker build -t fs7-fsl -f docker/Dockerfile .

# 2. Organize a delivery
python3 pipeline/1_ingest/dropbox_mri_to_bids.py /delivery/MRI --target_dir /data/batch12
python3 pipeline/1_ingest/dropbox_pet_to_bids.py /delivery/PET --target_dir /data/batch12

# 3. Structural processing (days — run under nohup)
python3 pipeline/2_freesurfer/processing_container.py /data/batch12/ADRC --license ~/license.txt
docker exec -it <container> bash
  nohup python3 mri_processing.py data/ > processing.log 2>&1 &

# 4. QC
python3 pipeline/4_qc/check_recon_all.py /data/batch12/ADRC

# 5. PET quantification
python3 pipeline/3_suvr/prepare_suvr_folder.py /data/batch12/ADRC --cores 8
python3 pipeline/3_suvr/registration.py        /data/batch12/ADRC --cores 8
python3 pipeline/3_suvr/suvr.py                /data/batch12/ADRC

# 6. Merge and aggregate
ADRC_ROOT=/data/NWSI/ADRC ./sync/sync_batch.sh 12
python3 scripts/suvr/make_suvr_symlink_farm.py --source /data/NWSI/ADRC --target /data/NWSI/suvr
python3 pipeline/5_aggregate/suvr_stats_all.py -sd /data/NWSI/suvr -o suvr_output
```

---

## Layout

| Path | Contents |
|---|---|
| [`pipeline/1_ingest/`](pipeline/1_ingest/) | Download, unzip, prefix, and reorganize raw deliveries |
| [`pipeline/2_freesurfer/`](pipeline/2_freesurfer/) | `recon-all` + hippocampal segmentation; container launcher |
| [`pipeline/3_suvr/`](pipeline/3_suvr/) | PET–MRI pairing, FLIRT registration, SUVR + Centiloid |
| [`pipeline/4_qc/`](pipeline/4_qc/) | Completeness and error checks |
| [`pipeline/5_aggregate/`](pipeline/5_aggregate/) | Study-level stats tables and reports |
| [`pipeline/6_extract/`](pipeline/6_extract/) | Pull scans back out by subject and date |
| [`sync/`](sync/) | Append-only rsync merges into the assembled dataset |
| [`docker/`](docker/) | Dockerfile and license template |
| [`docs/`](docs/) | The five guides |
| [`examples/`](examples/) | Input file formats and an annotated tree |

---

## Requirements

| | |
|---|---|
| **FreeSurfer 7.4.1** | `recon-all`, `segmentHA_T1.sh`, `mri_convert`, `*stats2table`. Needs a free [license](https://surfer.nmr.mgh.harvard.edu/registration.html). |
| **MATLAB Runtime R2019b** | Required by `segmentHA_T1.sh`. Installed by the Dockerfile. |
| **FSL** | `flirt`, for PET→MRI registration. |
| **Python 3.9+** | `nibabel`, `numpy`, `pandas`, `tqdm` — see [`requirements.txt`](requirements.txt). |
| **Docker** | Optional but recommended; the image provides all of the above. |

Environment variables: `FREESURFER_HOME`, `FSLDIR`, `CPU_CORES` (parallel job count, set
automatically by the container launcher), and `ADRC_ROOT` (dataset root, used by the extract and sync
scripts).

**Compute and storage are the real constraints.** `recon-all` is 8–12 hours per scan, and a full
cohort runs to roughly 1 TB. See [storage planning](docs/04-data-organization.md#storage-planning).

---

## Method summary

For the full treatment see [03-pet-centiloid.md](docs/03-pet-centiloid.md).

- PET is registered into FreeSurfer **conformed T1 space** (256³, 1 mm) with FSL FLIRT
  (12 DOF, `corratio`), and `aparc+aseg` is resampled onto the same grid — so regional values are
  read out directly, with no atlas warping or group template.
- **Reference region:** whole cerebellum (aseg labels 7, 8, 46, 47), volume-weighted. A cerebellar
  gray matter variant (labels 8, 47) is produced alongside.
- **Composite target ("Global"):** volume-weighted pool of anterior cingulate, posterior cingulate,
  frontal, temporal, and parietal regions across 34 Desikan–Killiany parcels.
- **Centiloid:**
  - Amyvid (¹⁸F-florbetapir): `CL = 183.07 × SUVR_global − 177.26`
  - Neuraceq (¹⁸F-florbetaben): `CL = 153.4 × SUVR_global − 154.9`
- Tracer is inferred from scan date (≥ 2016-09-27 → Neuraceq) unless `--compound` is given.
  **Per-subject exceptions are not implemented** — see
  [the warning](docs/03-pet-centiloid.md#-tracer-exceptions-are-not-implemented).

Known limitations are catalogued in
[05-troubleshooting.md](docs/05-troubleshooting.md#known-limitations). Read them before publishing
results.

---

## Data privacy

No subject data, scan, or identifier belongs in this repository.
[`.gitignore`](.gitignore) blocks imaging files, dataset directories, logs, and — importantly —
`license.txt`. A FreeSurfer license is a personal credential: never commit or share it. All subject
IDs and dates in the documentation and examples are synthetic.

---

## License

[MIT](LICENSE). FreeSurfer and FSL are installed at Docker build time and carry
their own licenses — review them before redistributing a built image. FSL in particular is free for
academic use only.
