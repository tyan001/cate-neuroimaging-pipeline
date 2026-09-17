# 2. FreeSurfer structural processing

`recon-all` plus hippocampal subfield and amygdala nuclei segmentation.

Full walkthrough: [docs/02-mri-processing.md](../../docs/02-mri-processing.md).

| Script | Purpose |
|---|---|
| `processing_container.py` | Launch a sized Docker container with the data and license mounted |
| `run_pipeline.py` | **Main entry point.** Runs `freesurfer_pipeline.py` + `hippocampus_pipeline.py` across subjects in parallel |
| `freesurfer_pipeline.py` | `recon-all` step only — usable standalone or imported by `run_pipeline.py` |
| `hippocampus_pipeline.py` | `segmentHA_T1.sh` step only — usable standalone or imported by `run_pipeline.py` |
| `pipeline_common.py` | Shared logging/path helpers used by the three scripts above |
| `mri_processing.py` | Original single-file version of the pipeline, kept as-is for reference |

The FreeSurfer and hippocampus steps used to live in one script (`mri_processing.py`).
They're now split so either stage can change independently — for example, swapping
the hippocampus tool or its arguments doesn't touch the FreeSurfer code at all.
`run_pipeline.py` just wires the two together in order and passes the FreeSurfer
output path straight into the hippocampus step, so there's a single source of truth
for that path instead of two scripts recomputing it separately.

---

## processing_container.py

```bash
python3 processing_container.py /path/to/ADRC --license /path/to/license.txt
```

| Flag | Default | Meaning |
|---|---|---|
| `directory` | — | Mounted at `/workspace/data` |
| `--name` | `fs-fsl` | Container name prefix → `<name>_<dirname>` |
| `--image` | `fs7-fsl` | Image to run |
| `--license` | `./license.txt` | FreeSurfer license path |

Counts `anat/*.nii` and allocates `min(n_scans + 1, host_cpus - 1)` CPUs, exporting the count as
`CPU_CORES` and the directory name as `CONTAINER_NAME`. Starts detached; attach with
`docker exec -it <name> bash`.

The license is bind-mounted read-only at `/usr/local/freesurfer/license.txt` — never baked into the
image, never committed.

## run_pipeline.py

```bash
# inside the container
nohup python3 run_pipeline.py data/ > processing.log 2>&1 &
```

Information of the hippocampus segmentation in this codebase can be found at [https://surfer.nmr.mgh.harvard.edu/fswiki/HippocampalSubfieldsAndNuclei](https://surfer.nmr.mgh.harvard.edu/fswiki/HippocampalSubfieldsAndNuclei).

There is also I python version of the hippocampus segmentation script that can be found at [https://surfer.nmr.mgh.harvard.edu/fswiki/SubregionSegmentation](https://surfer.nmr.mgh.harvard.edu/fswiki/SubregionSegmentation). NOT IMPLEMENTED IN THIS CODEBASE.



| Flag | Effect |
|---|---|
| *(none)* | `recon-all -all`, then `segmentHA_T1.sh`, for every scan |
| `--hc-only` | Only `segmentHA_T1.sh`, on existing `freesurfer741/` outputs |

Finds every `.nii` whose parent directory is named `anat`, then per subject:

```bash
recon-all -i <anat.nii> -subjid <filename-stem> -sd <session>/freesurfer741 -all
segmentHA_T1.sh <filename-stem> <session>/freesurfer741
```

Subjects run in parallel (`CPU_CORES` processes), the two steps run in sequence per subject —
`run_pipeline.py` calls into `freesurfer_pipeline.py` first, then, only if that succeeds,
`hippocampus_pipeline.py`, for each subject.

Output: `<subj>/<date>/freesurfer741/<anat-filename-stem>/` — a complete recon-all subject
directory. **The FreeSurfer subject ID is the anat filename without `.nii`**, so IDs are globally
unique and no central `SUBJECTS_DIR` is needed.

Logs: `<data-dir>/fs_logs/<CONTAINER_NAME or hostname>.log`.

**Runtime: 8–12 hours per scan** for `recon-all`, ~1 hour for the hippocampal step. Always run under
`nohup`.

### freesurfer_pipeline.py / hippocampus_pipeline.py

Each stage can also be run on its own, e.g. to redo just the hippocampal step after tweaking it,
without rerunning `recon-all`:

```bash
nohup python3 freesurfer_pipeline.py data/ > freesurfer.log 2>&1 &
nohup python3 hippocampus_pipeline.py data/ > hippocampus.log 2>&1 &
```

`freesurfer_pipeline.py` takes just a directory and runs `recon-all` across every `anat/*.nii` it
finds. `hippocampus_pipeline.py` takes just a directory and runs `segmentHA_T1.sh` across every
existing `freesurfer741/<subject>/` it finds (this is the same directory scan `run_pipeline.py
--hc-only` uses). Both write to the same `fs_logs/` log file convention as `run_pipeline.py`.

Their `process_subject_freesurfer()` / `process_subject_hippocampus()` functions are what
`run_pipeline.py` imports and calls directly, rather than shelling out to these scripts — the
FreeSurfer step's `fs_path` return value is passed straight into the hippocampus step so both
stages always agree on the `SUBJECTS_DIR`.

---

## mri_processing.py

The original, single-file version of this pipeline (recon-all + hippocampus segmentation
combined). Kept for reference / backward compatibility — prefer `run_pipeline.py` for new work,
since the FreeSurfer and hippocampus logic there can be changed independently. Usage and behavior
are identical to `run_pipeline.py` above.

---

**Notes.** The recon directory name is the literal string `freesurfer741` (in two places) — other
FS 7.x versions work but keep that folder name. Commands are built with `os.system()` and unquoted
f-strings, so avoid spaces in data paths.
