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
   │  prune extra SUVR registrations → symlink farms → study-level CSVs
   │  (aseg, aparc, hippocampus, amygdala, SUVR) → dataset counts
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

# 6. Merge into the dataset (plan first, then --execute)
python3 sync/merge_batch.py /data/batch12/ADRC --dest /data/NWSI/ADRC
python3 sync/merge_batch.py /data/batch12/ADRC --dest /data/NWSI/ADRC --execute

# 7. Keep only the MRI registration closest in time to each PET (dry run first)
python3 pipeline/5_aggregate/prune_suvr_registrations.py --source /data/NWSI/ADRC
python3 pipeline/5_aggregate/prune_suvr_registrations.py --source /data/NWSI/ADRC \
        --execute --quarantine /data/NWSI/suvr_pruned

# 8. Build the flat symlink farms (safe to rerun; add --dry-run to preview)
python3 pipeline/5_aggregate/freesurfer_symlink.py --source /data/NWSI/ADRC --target /data/NWSI/freesurfer_link
python3 pipeline/5_aggregate/suvr_symlink.py       --source /data/NWSI/ADRC --target /data/NWSI/suvr_link

# 9. Study-level tables (mri_stats_all.py needs FreeSurfer sourced)
python3 pipeline/5_aggregate/mri_stats_all.py  -fd /data/NWSI/freesurfer_link -o mri_output
python3 pipeline/5_aggregate/suvr_stats_all.py -sd /data/NWSI/suvr_link       -o suvr_output

# 10. How much is there, and how much is processed?
python3 pipeline/7_DirectoryStats/directory_data_count.py -i /data/NWSI

# 11. Scans that were never processed (new MRI, a PET whose MRI arrived later, ...)
python3 pipeline/7_DirectoryStats/find_missing.py         /data/NWSI/ADRC
python3 pipeline/7_DirectoryStats/process_missing.py all  /data/NWSI/ADRC --dry-run
```

`directory_data_count.py` counts the `anat/`, `ct/`, `pet/` and `modalities/` folders under
`ADRC/<subject>/<date>/`, then counts the entries in `freesurfer_link/` and `suvr_link/` and reports
any broken links. Comparing `anat` with `freesurfer_link`, or `pet` with `suvr_link`, shows how many
scans are still waiting to be processed.

---

## Development

The project uses [uv](https://docs.astral.sh/uv/) and Python 3.12. Dependencies are declared in
[`pyproject.toml`](pyproject.toml) and locked in [`uv.lock`](uv.lock).

```bash
uv sync                     # create .venv with runtime + dev (pytest, ruff) dependencies
uv run pytest               # run the test suite
uv run ruff check pipeline/1_ingest tests
```

`requirements.txt` lists the same runtime packages for the Docker image and plain `pip` installs.

**Tests.** [`tests/`](tests/) currently covers the ingest stage (`download.py`, `prefix.py`, and the
MRI/PET → BIDS converters). The tests do not need imaging data. They rebuild a tree of empty
placeholder files from [`tests/fixtures/ingest_data_manifest.txt`](tests/fixtures/ingest_data_manifest.txt).
If you have the local, gitignored `testdata/ingest_data/` and change it, regenerate the manifest:

```bash
python3 tests/fixtures/update_manifest.py
```

**CI.** [`.github/workflows/tests.yml`](.github/workflows/tests.yml) runs on every push to `main`
and on pull requests:

| Job | What it does |
|---|---|
| `ruff` | Lints `pipeline/1_ingest` and `tests` on Python 3.12. The rules are set in the workflow, not in a config file. |
| `1_ingest` | Runs the ingest tests on Python 3.12 and 3.13. |

Both jobs install with `uv sync --locked`, so CI fails if `uv.lock` is out of date with
`pyproject.toml`. Run `uv lock` after changing dependencies.

---

## Layout

| Path | Contents |
|---|---|
| [`pipeline/1_ingest/`](pipeline/1_ingest/) | Download, unzip, prefix, and reorganize raw deliveries |
| [`pipeline/2_freesurfer/`](pipeline/2_freesurfer/) | `recon-all` + hippocampal segmentation; container launcher |
| [`pipeline/3_suvr/`](pipeline/3_suvr/) | PET–MRI pairing, FLIRT registration, SUVR + Centiloid |
| [`pipeline/4_qc/`](pipeline/4_qc/) | Completeness and error checks |
| [`pipeline/5_aggregate/`](pipeline/5_aggregate/) | SUVR pruning, symlink farms, study-level stats tables, dataset counts |
| [`pipeline/6_extract/`](pipeline/6_extract/) | Pull scans back out by subject and date |
| [`pipeline/7_DirectoryStats/`](pipeline/7_DirectoryStats/) | Dataset counts; find MRI/PET scans that were never processed, and process just those |
| [`sync/`](sync/) | Append-only merges into the assembled dataset (`merge_batch.py` checks the batch first) |
| [`docker/`](docker/) | Dockerfile and license template |
| [`docs/`](docs/) | The five guides |
| [`examples/`](examples/) | Input file formats and an annotated tree |
| [`tests/`](tests/) | pytest suite (ingest and missing stages) and its fixture manifest |
| [`.github/workflows/`](.github/workflows/) | CI: ruff lint and ingest tests |
| `testdata/` | Local de-identified test set. **Gitignored**, never committed. |

---

## Requirements

| | |
|---|---|
| **FreeSurfer 7.4.1** | `recon-all`, `segmentHA_T1.sh`, `mri_convert`, `*stats2table`. Needs a free [license](https://surfer.nmr.mgh.harvard.edu/registration.html). |
| **MATLAB Runtime R2019b** | Required by `segmentHA_T1.sh`. Installed by the Dockerfile. |
| **FSL** | `flirt`, for PET→MRI registration. |
| **Python 3.12+** | `nibabel`, `numpy`, `pandas`, `tqdm`. See [`pyproject.toml`](pyproject.toml) or [`requirements.txt`](requirements.txt). |
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

### This repository: MIT

The code and documentation are under the [MIT License](LICENSE). Anyone may use, copy, modify and
share them free of charge, as long as they keep the copyright notice. The software comes with no
warranty.

This is a non-commercial academic research project. It is not sold, and no paid service is built on
it.

### Third-party software: its own licenses

The MIT license covers only the files written for this project. The tools the pipeline runs keep
their own licenses. The Docker image downloads them at build time, and this repository does not
include them.

| Software | License | What it means here |
|---|---|---|
| [FreeSurfer 7.4.1](https://surfer.nmr.mgh.harvard.edu/fswiki/FreeSurferSoftwareLicense) | FreeSurfer Software License | Free, but every user must [register](https://surfer.nmr.mgh.harvard.edu/registration.html) for their own `license.txt`. The license is personal. Never commit it, bake it into an image, or share it. |
| [FSL](https://fsl.fmrib.ox.ac.uk/fsl/fslwiki/Licence) | FSL licence | Free for non-commercial use, which covers this project. Commercial use requires a paid licence from the University of Oxford. |
| [MATLAB Runtime R2019b](https://www.mathworks.com/help/compiler/mcr-licensing.html) | MathWorks Runtime license | Free to install and use. The Dockerfile installs it through FreeSurfer's `fs_install_mcr`. |
| nibabel · numpy · pandas · tqdm | MIT · BSD-3-Clause · BSD-3-Clause · MPL-2.0 and MIT | Permissive. Installed from PyPI, not included in this repository. |

**Files from FreeSurfer that are included in this repository:**

- [`pipeline/5_aggregate/ConcatenateSubregionsResults`](pipeline/5_aggregate/ConcatenateSubregionsResults)
  is FreeSurfer's `quantifyData.sh` utility. It remains under the FreeSurfer license, not MIT.
- [`pipeline/3_suvr/FreesurferLUTR.txt`](pipeline/3_suvr/FreesurferLUTR.txt) is a subset of the
  label names in FreeSurfer's `FreeSurferColorLUT.txt`.

### Sharing the work

- **Share the Dockerfile, not a built image.** A built `fs7-fsl` image contains FreeSurfer, FSL and
  the MATLAB Runtime. Publishing it means redistributing all three under their terms. Anyone can
  build the image themselves with one command and their own FreeSurfer license.
- **Subject data is not covered by any software license.** Scans and derived outputs, including the
  CSVs from `5_aggregate`, are governed by the ADRC/NWSI data use agreements. Share them only as
  those agreements allow.
- **Cite the methods in publications.** FreeSurfer (Fischl, 2012), hippocampal subfields
  (Iglesias et al., 2015), amygdala nuclei (Saygin et al., 2017), FSL FLIRT (Jenkinson & Smith,
  2001; Jenkinson et al., 2002), and the Centiloid method (Klunk et al., 2015) with the tracer
  conversions (Navitsky et al., 2018 for florbetapir; Rowe et al., 2017 for florbetaben).
