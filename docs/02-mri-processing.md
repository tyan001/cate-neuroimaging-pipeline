# 2. Processing MRI scans

Takes structural MRI from vendor delivery through `recon-all` and hippocampal subfield segmentation.
The output is what every later stage depends on — PET quantification cannot run without it.

**Prerequisite:** a built image and a license ([01-environment.md](01-environment.md)).

```
raw delivery → ingest → BIDS-like layout → recon-all → segmentHA_T1.sh → QC
```

---

## Stage 1 — Ingest

Scans arrive as per-subject Dropbox zips accompanied by a CSV of share links. Four small scripts in
[`pipeline/1_ingest/`](../pipeline/1_ingest/) turn that into the directory layout everything else
assumes.

### 1a. Download

`download.py` reads a CSV with `name` and `link` columns, `curl`s each archive, unzips it, and
deletes the zip. See [`examples/dropbox_links.csv`](../examples/dropbox_links.csv).

```bash
python3 pipeline/1_ingest/download.py links.csv --type MRI --output-dir /path/to/batch12
```

`--type` is required and picks the output subfolder (`MRI/` or `PET/`). `--output-dir` is optional
and defaults to the current directory; pass it to land the files somewhere specific instead of
wherever you happened to run the command from.

If you already have the zips, skip this and use:

```bash
bash pipeline/1_ingest/unzip_files.sh /path/to/zips
```

which extracts each `foo.zip` into a sibling `foo/`.

### 1b. Add prefixes (only for some sites)

The converters key off folder names beginning `MRI_` or `PET_`. Some sites deliver folders without
them — at our sites this affects the UF grant subjects (IDs beginning `320`). Add them in bulk:

```bash
python3 pipeline/1_ingest/prefix.py /path/to/MRI --prefix MRI_ --dry-run   # preview
python3 pipeline/1_ingest/prefix.py /path/to/MRI --prefix MRI_             # apply
```

Already-prefixed folders are skipped, so re-running is safe. `--prefix` defaults to `MRI_`; pass
`PET_` for PET deliveries.

### 1c. Convert to the working layout

```bash
python3 pipeline/1_ingest/dropbox_mri_to_bids.py /path/to/MRI --target_dir /path/to/batch
```

Parses folder names of the form `MRI_<subjid>[-<session>]_<MMDDYYYY>` and produces:

```
<target>/ADRC/<subjid>/<YYYYMMDD>/
├── anat/        <subjid>-<YYYYMMDD>_T1w.nii     ← the scan recon-all will use
└── modalities/  every original file, untouched
```

The T1 is chosen by sniffing `*.<modality>.nii`: a `T1` series is preferred, `Cor_MPRAGE` is the
fallback when no T1 exists, producing `_CorMPRAGE.nii` instead. Everything from the delivery —
DTI, FLAIR, SWI, resting-state, and their dcm2niix JSON/bval/bvec sidecars — is preserved verbatim
in `modalities/`. Nothing is discarded.

Logs land in `<target>/logs/mri_bids_logs/`.

> **Known issue.** The chosen T1 is latched per *subject*, not per *session*. If one run converts a
> subject with several sessions, the first session's T1 is reused for the later ones. Convert
> multi-session subjects one session at a time, or verify `anat/` afterwards with
> `pipeline/5_aggregate/anat_report.py`.

Verify the result before spending CPU-days on it:

```bash
python3 pipeline/5_aggregate/anat_report.py /path/to/batch/ADRC -o anat_check.csv
```

This lists every `anat/` file with its parsed subject, date, and modality — an easy way to spot
missing or misnamed scans.

---

## Stage 2 — Launch the container

```bash
python3 pipeline/2_freesurfer/processing_container.py /path/to/batch/ADRC \
    --license /path/to/license.txt

docker ps                              # find the container name
docker exec -it <container_name> bash
```

The dataset is mounted at `/workspace/data` and `CPU_CORES` is set from the scan count. Details in
[01-environment.md](01-environment.md#launch-a-processing-container).

---

## Stage 3 — recon-all + hippocampal segmentation

Inside the container:

```bash
cd /workspace
nohup python3 mri_processing.py data/ > processing.log 2>&1 &
```

`nohup ... &` matters. A full run takes days and must survive your SSH session closing.

### What it does

[`mri_processing.py`](../pipeline/2_freesurfer/mri_processing.py) finds every `.nii` whose parent
directory is named `anat`, then runs two commands per subject **in sequence**:

```bash
recon-all -i <anat.nii> -subjid <scan-filename-stem> -sd <session>/freesurfer741 -all
segmentHA_T1.sh <scan-filename-stem> <session>/freesurfer741
```

Subjects run **in parallel**, one process per `CPU_CORES`. Two consequences worth internalizing:

- The **FreeSurfer subject ID is the anat filename without `.nii`** — e.g. `110001-20200115_T1w`.
  It embeds subject and date, so IDs are globally unique and no central `SUBJECTS_DIR` is needed.
- Each session gets its **own** `freesurfer741/` directory holding one recon. Outputs live beside
  the data they came from, not in a shared subjects tree.

```
ADRC/110001/20200115/
├── anat/110001-20200115_T1w.nii
└── freesurfer741/110001-20200115_T1w/
    ├── mri/     T1.mgz, aparc+aseg.mgz, hippoAmygLabels-T1.v22.*
    ├── surf/    lh.pial, rh.white, ...
    ├── label/
    ├── stats/   aseg.stats, ?h.aparc.stats, hipposubfields.?h.T1.v22.stats, ...
    └── scripts/ recon-all.log, recon-all.error (only on failure)
```

### Runtime

`recon-all -all` is **8–12 hours per scan** on a typical core; `segmentHA_T1.sh` adds roughly another
hour. With N cores you process N scans concurrently, so a 100-scan batch on 16 cores takes about
three days. Plan accordingly — this is the long pole of the whole pipeline.

### Flags

| Flag | Effect |
|---|---|
| *(none)* | `recon-all` then `segmentHA_T1.sh`, for every scan found |
| `--hc-only` | Skip `recon-all`; run only `segmentHA_T1.sh` on existing `freesurfer741/` outputs |

`--hc-only` is how you recover when recons succeeded but hippocampal segmentation did not — usually
an MCR problem.

### Logs

Progress goes to `<data-dir>/fs_logs/<CONTAINER_NAME or hostname>.log`, with per-step timings and a
success/failure summary at the end. FreeSurfer's own verbose output stays in each subject's
`scripts/recon-all.log`.

---

## Stage 4 — QC

Never assume a batch finished cleanly. Run both checks from
[`pipeline/4_qc/`](../pipeline/4_qc/):

```bash
# Which recons hit an error?  (looks for scripts/recon-all.error)
python3 pipeline/4_qc/check_recon_all.py /path/to/batch/ADRC

# Which recons are missing hippocampal output?
python3 pipeline/4_qc/check_hippocampus.py /path/to/batch/ADRC

# Which sessions have an anat/ but no freesurfer741/ at all?
python3 pipeline/4_qc/check_mri_missing_processing.py /path/to/batch/ADRC
```

The third catches scans that were never picked up — a misnamed `anat/` directory, or a scan added
after the run started.

**Recovering:**

- *Hippocampus missing, recon fine* → re-run with `--hc-only`.
- *`recon-all.error` present* → read `scripts/recon-all.log`, fix or exclude the scan, delete the
  failed subject directory, and re-run. `recon-all` will not restart cleanly over a partial output.
- *Session missing entirely* → check the `anat/` filename matches
  `<subjid>-<YYYYMMDD>_<T1w|CorMPRAGE>.nii`.

See [05-troubleshooting.md](05-troubleshooting.md) for specific failure modes.

You may also want to confirm the T1s are genuinely isotropic before trusting cortical thickness:

```bash
python3 pipeline/4_qc/check_mprage.py /path/to/batch/ADRC -o isotropic.csv
```

---

## Next

- **PET on these subjects** → [03-pet-centiloid.md](03-pet-centiloid.md)
- **Merge the batch into the main dataset** → [04-data-organization.md](04-data-organization.md)
- **Study-level stats tables** → [`pipeline/5_aggregate/README.md`](../pipeline/5_aggregate/README.md)
