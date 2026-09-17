# 6. Finding and viewing scans

Look up a subject's sessions and inspect any volume in them. Nothing here modifies the dataset.

Both scripts take `-r/--root` for the dataset folder, or fall back to `$ADRC_ROOT`:

```bash
export ADRC_ROOT=/data/NWSI/ADRC
```

| Script | Purpose |
|---|---|
| `viewer.py` | Browser viewer: search a subject, browse sessions, inspect volumes |
| `scans.py` | Command-line lookup, and the library the viewer uses |

Dates are accepted as `MM/DD/YYYY`, `YYYY-MM-DD` or `YYYYMMDD`.

---

## viewer.py

```bash
python3 viewer.py                                          # uses $ADRC_ROOT
python3 viewer.py -r /data/NWSI/ADRC -r /data/batch12/ADRC   # offer several datasets
python3 viewer.py --port 9000
```

The viewer is a small local web server, so it works on a headless server. It listens on localhost
only. From your laptop, forward the port and open the page:

```bash
ssh -L 8765:localhost:8765 you@server
# then browse to http://localhost:8765
```

**Dataset.** Paste any path into the *Dataset* box and press *Open*. The page opens at the level
of that path:

| Pasted path | Opens |
|---|---|
| `/mnt/backup/dev/NWSI/ADRC` | the dataset |
| `/mnt/backup/dev/NWSI/ADRC/900004` | that subject, with its first session |
| `/mnt/backup/dev/NWSI/ADRC/900004/20150527` (or any folder inside it) | that session |
| `/mnt/backup/dev/NWSI/ADRC/900004/20150527/pet/900004-20150527_PET.nii` | that scan |

The dataset is the folder above `<subject>/<YYYYMMDD>`, so any tree with that layout works. The
suggestion list offers the `--root` folders plus the last 10 paths opened in your browser. If the
server was started without a root, the page reopens the last dataset you used.

**Finding scans.** Type a subject ID (it autocompletes) and press *Find*. Every session folder is
listed with chips for the scans it holds: T1w, CorMPRAGE, PET (with a count when `_PET_128`-style
variants exist) and CT. The *T1w* and *PET* filters hide sessions without that scan. Opening a
session shows every `.nii`, `.nii.gz` and `.mgz` in it, grouped by folder (`anat/`, `pet/`,
`modalities/`, `freesurfer741/.../mri/`, `suvr/...`), and loads its main scan. Files of 0 bytes are
marked *empty*.

**Inspecting a volume.**

- Axial, coronal and sagittal views, reoriented to RAS whatever the file's own orientation.
  The views are neurological by default (left on the left); tick *Radiological* to flip them.
- Cursor readout: voxel index, world coordinates in mm, and the voxel value.
- Window/level from the number boxes, the *Auto* (0.5–99.5 percentile) and *Full* buttons, or a
  right-drag on any view.
- Colormaps: gray, hot, inferno, viridis, and *labels*. Segmentations such as `aparc+aseg.mgz`
  open in *labels*, with one color per label value.
- 4D files (dynamic PET, DTI) get a frame picker, including *mean of all frames*.
- Info panel: intensity histogram, min/max/mean, header fields (shape, voxel size, dtype,
  orientation, qform/sform codes, scaling, description), the affine, and the JSON sidecar when
  `<same-name>.json` exists.
- Empty or unreadable files show the reason instead of an image.

| Control | Action |
|---|---|
| click / drag | move the cursor |
| wheel, ↑ ↓, PgUp PgDn | change the slice in the view under the mouse |
| right-drag (or shift-drag) | window: ↔ width, ↕ level |
| double-click a view | enlarge it; double-click again to restore |
| `[` `]` | previous / next session |
| `,` `.` | previous / next file in the session |
| ‹ › next to the subject box | previous / next subject |

The URL records the dataset, subject, session and file, so you can bookmark a scan or send the link
to someone else who has the same port forward.

**Transfer size.** A volume is sent as 16-bit values, gzip-compressed: about 10–20 MB for a 1 mm
T1w. Float data (PET) is scaled to 65,536 levels over its full range, and integer data is sent
exactly. The readout for float volumes is therefore accurate to about 1/65,536 of the data range.

## scans.py

```bash
python3 scans.py 900001                       # sessions, with the T1w/PET/CT in each
python3 scans.py 900001 01/15/2020            # every volume in that session
python3 scans.py 900001 01/15/2020 -t t1w     # just the path(s), one per line
```

`-t` accepts `t1w`, `mprage` (`_CorMPRAGE`), `pet` and `ct`. The script exits with status 1 when
the subject, session or scan is missing, so `-t` output can be used in shell scripts.

As a library, it provides `parse_date`, `list_subjects`, `list_sessions`, `find_scans` and
`session_volumes`. `find_scans` implements the naming contract below. It also matches
reconstruction variants (`_PET_128`, `_PET_a`, …) and `.nii.gz`/`.mgz`, and returns the exact name
first:

```
<root>/<pid>/<YYYYMMDD>/anat/<pid>-<YYYYMMDD>_T1w.nii
<root>/<pid>/<YYYYMMDD>/pet/<pid>-<YYYYMMDD>_PET.nii
<root>/<pid>/<YYYYMMDD>/ct/<pid>-<YYYYMMDD>_CT.nii
```
