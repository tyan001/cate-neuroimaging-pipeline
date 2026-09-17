# Missing: find and process scans that were never processed

Scans get added to the dataset after a batch has run, or an MRI shows up months after its PET. The
regular stages run on a whole batch folder. These two scripts check the assembled dataset and run
only the scans that are still unprocessed.

| Script | Purpose |
|---|---|
| `find_missing.py` | Report: the status of every MRI and PET scan. Changes nothing. |
| `process_missing.py` | Runs FreeSurfer and SUVR on the scans the report marks as runnable, and nothing else |
| `inventory.py` | The shared scan-and-classify logic both scripts use |
| `merge_batch.py` | Checked, append-only merge of a processed batch into the main folder (see [`sync/README.md`](../../sync/README.md)) |
| `directory_data_count.py` | Folder and symlink-farm counts for the whole dataset |

The processing itself is not reimplemented. `process_missing.py` calls
`2_freesurfer/dev` (`process_subject_freesurfer`, `process_subject_hippocampus`) and the
`3_suvr/dev/OOP` stages (`PrepareStage`, `RegisterStage`, `QuantifyStage`). Output locations,
file names and logs are the same as when those stages run on a batch.

```bash
# 1. What is missing? (runs anywhere; no FreeSurfer needed)
python3 find_missing.py --root /path/to/ADRC
python3 find_missing.py --root /path/to/ADRC --csv missing.csv

# 2. What would run?
python3 process_missing.py all /path/to/ADRC --dry-run

# 3. Run it, inside the fs7-fsl container
nohup python3 directory_stats/process_missing.py all data/ --cores 8 > missing.log 2>&1 &
```

---

## How a scan is classified

### MRI: every `<subject>/<session>/anat/*.nii`

| Status | Meaning | `process_missing.py` |
|---|---|---|
| `no_freesurfer` | No `freesurfer741/<scan stem>/` folder: recon-all never ran | `recon-all -all`, then `segmentHA_T1.sh` |
| `no_hippocampus` | Recon finished, but no `stats/hipposubfields.{lh,rh}.T1.v22.stats` | `segmentHA_T1.sh` only |
| `recon_failed` | `scripts/recon-all.error` exists | Reported only |
| `recon_incomplete` | The folder exists but `T1.mgz`, `aparc+aseg.mgz` or the aseg/aparc stats are missing. Either the run is still going or it was killed. | Reported only |
| `wrong_session` | The filename date does not match the session folder (e.g. `900071/20250826/anat/900071-20240821_T1w.nii`) | Reported only |
| `complete` | | |

A recon counts as finished when its output files exist, not when a done-marker is present, so
the check does not depend on the FreeSurfer version.

`recon_failed` and `recon_incomplete` are never rerun automatically. `recon-all -i` refuses to
start over an existing subject folder, and a partial folder can also mean a run is still in
progress. Check `scripts/recon-all.log`, delete the folder, and the next run will classify the
scan as `no_freesurfer`.

`wrong_session` files are left for you to deal with. Such a file is usually a copy of another
session's scan, made by the ingest step for subjects with several sessions (see the xfail tests in
`tests/ingest`). Processing it would repeat that session's 8–12 hour recon.

### PET: every `<subject>/<session>/pet/*_PET*.nii`

Each PET is paired with the subject's **closest-dated** T1w/CorMPRAGE scan, the same rule
`prepare` uses.

| Status | Meaning | `process_missing.py` |
|---|---|---|
| `waiting_for_mri` | The subject has no MRI yet | Reported only |
| `waiting_for_freesurfer` | The closest MRI has no finished recon | `all`: processed after the MRI step, if that recon succeeds |
| `no_suvr` | No pair folder exists for (this PET, closest MRI) | prepare → register → quantify |
| `incomplete_suvr` | The pair folder exists but has no `res/<pair>_suvr_combined_cerebellum.csv` | prepare → register → quantify (existing outputs are kept) |
| `bad_name` | The filename is not `<subj>-<YYYYMMDD>_PET[_extra].nii` | Reported only |
| `wrong_session` | The filename date does not match the session folder | Reported only |
| `complete` | | |

The hippocampal step is not needed for SUVR. A PET can therefore be processed while its MRI is
still `no_hippocampus`.

**When a closer MRI arrives later.** Suppose a PET was paired with a 2017 MRI, and a 2025 MRI has
since been processed. The PET now shows as `no_suvr`, with the detail `also paired with
<old pair folder>`, and `process_missing.py` builds the new pair beside the old one. Afterwards,
run `5_aggregate/prune_suvr_registrations.py` to keep only the closest pair.

---

## find_missing.py

```bash
python3 find_missing.py [--root /path/to/ADRC] [--subject ID ...] [--csv FILE] [--all]   # --root defaults to $ADRC_ROOT
```

Prints a count per status, lists every scan whose status is not `complete` (use `--all` to list
the complete ones too), and ends with a one-line summary of what `process_missing.py` would run.
`--csv` writes one row per scan with the columns
`modality, subject, session, scan, status, action, paired_mri, detail`.

It does not need FreeSurfer or FSL. It is read-only and fast: it looks only at the fixed
`<subject>/<session>/{anat,pet}` depth (about 0.5 s for the 780-subject dataset).

## process_missing.py

```bash
python3 process_missing.py {mri,suvr,all} /path/to/ADRC [options]
```

| Stage | Runs |
|---|---|
| `mri` | recon-all + hippocampus for `no_freesurfer`; hippocampus only for `no_hippocampus` |
| `suvr` | prepare → register → quantify for `no_suvr` / `incomplete_suvr`. A pair whose prepare step fails is not passed to register or quantify. |
| `all` | `mri`, then checks the PET scans again and runs `suvr`, so PET scans unblocked by the MRI step are processed in the same run |

| Flag | Meaning |
|---|---|
| `--dry-run` | Print the plan (including PET scans that will be processed after the MRI step, and the ones that will not be processed at all) and exit |
| `--subject ID` | Limit to a subject; repeatable |
| `--cores N` | Parallel workers (default `$CPU_CORES`, else 1). MRI: one recon per worker. SUVR: one pair per worker. |
| `--no-hippocampus` | `mri`: skip `segmentHA_T1.sh` (e.g. when the MATLAB Runtime is unavailable) |
| `--compound amyvid\|neuraceq` | `suvr`: force the tracer (otherwise picked by scan date, as in `3_suvr`) |
| `--lut PATH` | `suvr`: ROI table (default `3_suvr/FreesurferLUTR.txt`) |

Before doing any work, the script checks that `recon-all`/`segmentHA_T1.sh` or
`mri_convert`/`*stats2table` are on `PATH`.

**Logs.** A log for the whole run goes to `<root>/logs/missing_logs/process_missing_<timestamp>.log`.
The SUVR stages also write their usual per-task logs inside the data tree, and recon-all
writes to each subject's `scripts/`. The exit code is nonzero if any recon, hippocampal
segmentation or SUVR task failed.

**Caveat.** `quantify` writes `res/` even when the cerebellum reference SUV is ≤ 0. It marks the
task as failed in this run, but the next `find_missing.py` will call that PET `complete`. Check the
failure list at the end of the log.

### Running in the container

The Dockerfile copies this folder to `/workspace/directory_stats/`, beside `/workspace/dev/`
(FreeSurfer) and `/workspace/suvr/` (SUVR). The scripts find both locations, repo and
container, on their own.

```bash
python3 pipeline/2_freesurfer/processing_container.py /data/NWSI/ADRC --license ~/license.txt
docker exec -it <container> bash
  python3 directory_stats/process_missing.py all data/ --dry-run
  nohup python3 directory_stats/process_missing.py all data/ > missing.log 2>&1 &
```

`processing_container.py` sets the CPU count from the number of `anat/*.nii` files. On the full
dataset that means every core but one, which is also what `--cores` will default to.
