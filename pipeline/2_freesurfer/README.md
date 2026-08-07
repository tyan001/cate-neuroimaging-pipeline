# 2. FreeSurfer structural processing

`recon-all` plus hippocampal subfield and amygdala nuclei segmentation.

Full walkthrough: [docs/02-mri-processing.md](../../docs/02-mri-processing.md).

| Script | Purpose |
|---|---|
| `processing_container.py` | Launch a sized Docker container with the data and license mounted |
| `mri_processing.py` | Run `recon-all` + `segmentHA_T1.sh` across subjects in parallel |

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

The license is bind-mounted read-only at `/usr/local/freesurfer/.license` — never baked into the
image, never committed.

## mri_processing.py

```bash
# inside the container
nohup python3 mri_processing.py data/ > processing.log 2>&1 &
```

| Flag | Effect |
|---|---|
| *(none)* | `recon-all -all`, then `segmentHA_T1.sh`, for every scan |
| `--hc-only` | Only `segmentHA_T1.sh`, on existing `freesurfer741/` outputs |

Finds every `.nii` whose parent directory is named `anat`, then per subject:

```bash
recon-all -i <anat.nii> -subjid <filename-stem> -sd <session>/freesurfer741 -all
segmentHA_T1.sh <filename-stem> <session>/freesurfer741
```

Subjects run in parallel (`CPU_CORES` processes), the two steps run in sequence per subject.

Output: `<subj>/<date>/freesurfer741/<anat-filename-stem>/` — a complete recon-all subject
directory. **The FreeSurfer subject ID is the anat filename without `.nii`**, so IDs are globally
unique and no central `SUBJECTS_DIR` is needed.

Logs: `<data-dir>/fs_logs/<CONTAINER_NAME or hostname>.log`.

**Runtime: 8–12 hours per scan** for `recon-all`, ~1 hour for the hippocampal step. Always run under
`nohup`.

---

**Notes.** The recon directory name is the literal string `freesurfer741` (in two places) — other
FS 7.x versions work but keep that folder name. Commands are built with `os.system()` and unquoted
f-strings, so avoid spaces in data paths.
