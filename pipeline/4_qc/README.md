# 4. Quality control

Run these after every structural batch. `mri_processing.py` reports a summary, but it cannot see
failures FreeSurfer wrote to disk after the fact, and it never notices scans it did not pick up.

All four take a dataset root and print a report.

| Script | Answers |
|---|---|
| `check_recon_all.py` | Which recons hit an error? |
| `check_hippocampus.py` | Which recons lack hippocampal segmentation? |
| `check_mri_missing_processing.py` | Which sessions have an `anat/` but no `freesurfer741/`? |
| `check_mprage.py` | Which T1s are genuinely isotropic? |

---

## check_recon_all.py

```bash
python3 check_recon_all.py /path/to/ADRC
```

Globs `*/*/freesurfer741/*/scripts/recon-all.error` and lists every subject that produced one, with
a count. Also reports which subjects have a completed `hippocampal-subfields-T1.log`.

A subject listed here needs its output directory deleted before re-running — `recon-all` does not
resume cleanly over a partial result.

## check_hippocampus.py

```bash
python3 check_hippocampus.py /path/to/ADRC
```

Compares subjects with `scripts/hippocampal-subfields-T1.log` against all `freesurfer741/` outputs
and prints the difference — i.e. exactly which recons still need the hippocampal step. Recover with:

```bash
python3 ../2_freesurfer/mri_processing.py /path/to/ADRC --hc-only
```

Missing output here usually means the MATLAB Runtime is absent or `LD_LIBRARY_PATH` is wrong; see
[docs/05-troubleshooting.md](../../docs/05-troubleshooting.md#hippocampal-segmentation-missing-or-failing).

## check_mri_missing_processing.py

> **Takes the PARENT of the dataset root**, unlike every other script here. It globs `**/ADRC`, so
> pointing it at the `ADRC` directory itself prints "No ADRC folders found" and exits successfully —
> an easy silent no-op to miss.

```bash
python3 check_mri_missing_processing.py /path/to        # NOT /path/to/ADRC
```

Per subject and session, flags sessions with no `anat/` at all, and sessions that have an `anat/` but
no `freesurfer741/`. This catches scans that were never processed — a misnamed directory, a scan
added after the run started, or a filename that does not match
`<subjid>-<YYYYMMDD>_<T1w|CorMPRAGE>.nii`.

## check_mprage.py

```bash
python3 check_mprage.py /path/to/ADRC -o isotropic_matrix_files.csv
```

Loads every NIfTI under `anat/` with `nibabel` and flags those whose matrix dimensions are equal on
all three axes. Non-isotropic acquisitions degrade cortical thickness estimates — worth knowing
before results go into an analysis.
