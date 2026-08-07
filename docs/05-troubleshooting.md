# 5. Troubleshooting

---

## Environment

### `FileNotFoundError: ... FreesurferLUTR.txt`

`suvr.py` loads the ROI label table from its own directory. Confirm
`pipeline/3_suvr/FreesurferLUTR.txt` exists and travels with `suvr.py` whenever you copy it
somewhere. In the container:

```bash
ls /workspace/suvr/FreesurferLUTR.txt
```

### `ModuleNotFoundError: No module named 'nibabel'` (or pandas / numpy / tqdm)

The image installs these from `requirements.txt`. If you built an older image or are running
natively:

```bash
pip3 install -r requirements.txt
```

### `EnvironmentError: FreeSurfer installation not found at ...`

`prepare_suvr_folder.py` checks that `$FREESURFER_HOME` points at a real directory, defaulting to
`/usr/local/freesurfer`. Set it:

```bash
export FREESURFER_HOME=/your/freesurfer
source $FREESURFER_HOME/SetUpFreeSurfer.sh
```

### `flirt: command not found`

Set `FSLDIR` and source the config; `registration.py` appends `$FSLDIR/bin` to `PATH` but cannot
invent the location.

```bash
export FSLDIR=/usr/local/fsl
source $FSLDIR/etc/fslconf/fsl.sh
```

### License errors from `recon-all`

`ERROR: FreeSurfer license file ... not found` means the bind mount is missing or wrong.
`processing_container.py` mounts your license at `/usr/local/freesurfer/.license`. Verify inside the
container:

```bash
cat /usr/local/freesurfer/.license     # four lines: email, ID, two keys
```

`processing_container.py` also refuses to start if the file is missing or empty, so an error there
means the `--license` path is wrong. Get a license at
<https://surfer.nmr.mgh.harvard.edu/registration.html>.

### Docker build fails on certificates

Institutional TLS interception. Add `--skip_ssl_verify` to the `fslinstaller.py` call and
`--no-check-certificate` to the FreeSurfer `wget` — both lines are commented in
[`docker/Dockerfile`](../docker/Dockerfile). Only on a network you trust.

---

## MRI processing

### The script finds no subjects

`mri_processing.py` collects `.nii` files whose **parent directory is named exactly `anat`**. Check:

```bash
find /path/to/ADRC -type d -name anat | head
find /path/to/ADRC -path '*/anat/*.nii' | head
```

Common causes: pointing at the wrong level (pass the directory *containing* subject folders), a
capitalized `Anat/`, or `.nii.gz` files (the patterns expect uncompressed `.nii`).

### `recon-all.error` present

Read the tail of `freesurfer741/<subject>/scripts/recon-all.log` — the real failure is there.
Frequent causes: truncated or corrupt input, severe motion, non-isotropic acquisition, and
out-of-memory when too many recons run concurrently.

**`recon-all` will not resume cleanly over a partial output.** Delete the subject directory before
re-running:

```bash
rm -rf /path/to/ADRC/110001/20200115/freesurfer741/110001-20200115_T1w
```

Reduce `CPU_CORES` if failures correlate with concurrency.

### Hippocampal segmentation missing or failing

`segmentHA_T1.sh` is a compiled MATLAB program requiring MCR R2019b. Verify:

```bash
ls $FREESURFER_HOME/MCRv97
echo $LD_LIBRARY_PATH        # must include the MCRv97 runtime paths
```

Re-run just this step on completed recons:

```bash
python3 mri_processing.py /workspace/data --hc-only
```

### Finding what's incomplete

```bash
python3 pipeline/4_qc/check_recon_all.py /path/to/ADRC              # recon-all.error files
python3 pipeline/4_qc/check_hippocampus.py /path/to/ADRC            # missing hippocampal output
python3 pipeline/4_qc/check_mri_missing_processing.py /path/to/ADRC # anat/ but no freesurfer741/
```

---

## PET / SUVR

### No SUVR folders are created

`prepare_suvr_folder.py` requires, for a given subject: a session containing `pet/` with a file
matching `*_PET*.nii`, **and** at least one `anat/` file matching `*T1w*` or `*CorMPRAGE*`, **and** a
completed `freesurfer741/<mri_stem>/` for that MRI. Missing any one produces nothing, quietly.

```bash
ls /path/to/ADRC/110001/*/pet/
ls /path/to/ADRC/110001/*/anat/
ls -d /path/to/ADRC/110001/*/freesurfer741/*/
```

### Far more pair folders than expected

Working as designed — every PET is paired with every MRI session. 4 PET × 5 MRI = 20 folders. See
[03-pet-centiloid.md](03-pet-centiloid.md#every-pet-is-paired-with-every-mri).

### `mri_convert` or `aparcstats2table` failures

These run with `SUBJECTS_DIR` set to the session's `freesurfer741/` directory. Failures usually mean
the recon is incomplete — check for `stats/aseg.stats` and `mri/aparc+aseg.mgz` before blaming the
tool.

### Registration looks wrong

Inspect before trusting a batch:

```bash
fsleyes MRI/<subj>-<date>_T1w.nii register_scan/<subj>-<date>_reg_<subj>-<date>_T1w.nii -cm hot -a 40
```

FLIRT runs at 12 DOF with a ±90° search. Gross misalignment usually means the PET was already in a
different orientation than expected, or the wrong file was picked up as the reference. Delete the
bad output and re-run — the step skips existing outputs, so a stale bad result will persist
otherwise.

### Centiloid values look implausible

Work backwards:

1. **Check the tracer.** `Compound` is in the combined CSV. It is assigned from the scan date
   (≥ 2016-09-27 → Neuraceq), and **per-subject exceptions are not implemented**. Re-run affected
   subjects with an explicit `--compound`.
2. **Check the reference.** `<combo>_suv_cer` is the whole-cerebellum reference value. Near zero or
   wildly off means the segmentation and PET are misaligned, or the cerebellum was cropped out of
   the PET field of view.
3. **Check `Global`.** Centiloid is a linear function of it, so an implausible CL means an
   implausible Global SUVR — go back to the registration.

### `AttributeError` on a generator in `suvr.py`

Around line 586 a fallback for locating `register_scan/` assigns a generator and then calls `.glob()`
on it. You only reach this when the directory layout differs from what `prepare_suvr_folder.py`
produces. Re-run step 1 rather than hand-building folders.

---

## Known limitations

Carried forward deliberately — these are documented, not fixed.

| Limitation | Where | Impact |
|---|---|---|
| Tracer exceptions not implemented | `suvr.py` `determine_compound()` | Wrong Centiloid equation for subjects who received the non-default tracer. SUVRs unaffected. |
| Older results used unweighted hemisphere averaging | `suvr.py` (historical) | Pairs processed before the volume-weighting change have different bilateral and `Total` SUVRs. Centiloid barely moves. [Details and how to detect it.](03-pet-centiloid.md#results-produced-before-this-change-differ) |
| Only two tracers supported | `suvr.py` `calculate_centiloid()` | PiB, flutemetamol, NAV4694 need coefficients added. |
| `2016-09-27` cutoff is site-specific | `suvr.py` | Meaningless for other cohorts — change it or always pass `--compound`. |
| `Total` includes corpus callosum | `suvr.py` (labels 1004/2004) | Affects `Total` only, not `Global` or Centiloid. |
| 12-DOF PET→MRI registration | `registration.py` | Full affine where 6-DOF rigid is conventional within-subject. |
| No partial-volume correction | `suvr.py` | Expect PVE-driven underestimation in thin cortex. |
| `freesurfer741` hardcoded | `mri_processing.py`, `prepare_suvr_folder.py` | Works with other FS 7.x, but the folder name stays `freesurfer741`. |
| `ADRC` hardcoded as output dir | `dropbox_{mri,pet}_to_bids.py` | Cohort folder name is a string literal. |
| T1 latched per subject, not per session | `dropbox_{mri,pet}_to_bids.py` | Multi-session subjects converted in one run reuse the first session's T1. Convert one session at a time. |
| `os.system` with unquoted paths | `mri_processing.py` | Paths containing spaces break. Avoid spaces in data paths. |
| PET/CT filename patterns are site-specific | `dropbox_pet_to_bids.py` | Edit the pattern lists for your scanner's naming. |

---

## Getting more detail

Most scripts take `-v` / `--verbose`. Logs are written at four levels — see
[04-data-organization.md](04-data-organization.md#logs) for where each stage writes.

For the SUVR stages, `--disable-parallel` (step 1) and `--single` / `--single-subject` make failures
far easier to read, since worker exceptions in a process pool tend to surface without useful context.
