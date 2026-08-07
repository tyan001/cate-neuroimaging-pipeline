# 3. PET quantification — SUVR and Centiloid

Requires completed `recon-all` output for the subject's MRI. Run the three scripts in order on the
same directory.

Full walkthrough, including the ROI definitions and Centiloid equations:
[docs/03-pet-centiloid.md](../../docs/03-pet-centiloid.md).

```bash
python3 prepare_suvr_folder.py /path/to/ADRC --cores 8
python3 registration.py        /path/to/ADRC --cores 8
python3 suvr.py                /path/to/ADRC
```

| File | Purpose |
|---|---|
| `prepare_suvr_folder.py` | Build PET×MRI pair folders; convert volumes; export FreeSurfer volume stats |
| `registration.py` | FSL FLIRT, PET into FreeSurfer T1 space |
| `suvr.py` | Per-ROI SUV → SUVR → Centiloid |
| `FreesurferLUTR.txt` | **Required data file** — 116-row ROI label→name table, loaded by `suvr.py` from its own directory. Keep it beside `suvr.py`. |

---

## prepare_suvr_folder.py

| Flag | Meaning |
|---|---|
| `--cores N` | Worker processes |
| `--parallel-mode subjects\|combinations` | Parallelize over subjects (default) or pairs |
| `--disable-parallel` | Serial, for debugging |
| `--single-subject <id>` | One subject |
| `-v` | Verbose |

Builds the **full cross-product** of every PET × every MRI session per subject — 4 PET × 5 MRI = 20
pair folders. Deliberate: it defers the pairing choice to analysis time.

```
<subj>/<PETdate>/suvr/<subj>-<PETdate>_PET/<subj>_pet_<PETdate>_mri_<MRIdate>/
├── MRI/            T1.nii, aparc+aseg.nii, PET.nii, 3 volume CSVs
├── register_scan/  (step 2)
└── res/            (step 3)
```

Converts `T1.mgz` and `aparc+aseg.mgz` with `mri_convert -ot nii --out_orientation RAS` — same
orientation for both, which is what makes direct voxel indexing valid. Exports volumes via
`aparcstats2table` / `asegstats2table`; `suvr.py` uses those as pooling weights.

Reads `$FREESURFER_HOME` (default `/usr/local/freesurfer`).

## registration.py

| Flag | Meaning |
|---|---|
| `--cores N` | Worker processes (default 4, one subject each) |
| `--single` | One subject |
| `--verbose` | Verbose |

```bash
flirt -in <PET> -ref <T1> -out <out>.nii -omat <out>.mat \
      -bins 256 -cost corratio -searchr{x,y,z} -90 90 -dof 12 -interp trilinear
```

Writes `register_scan/<subj>-<PETdate>_reg_<subj>-<MRIdate>_<modality>.nii` + `.mat`. Skips existing
outputs, so it resumes cleanly — but that also means a bad result persists until you delete it.

Reads `$FSLDIR` (default `/usr/local/fsl`); forces `FSLOUTPUTTYPE=NIFTI`.

> 12 DOF is a full affine. Within-subject PET→MRI conventionally uses 6-DOF rigid. This matches the
> implementation these results were validated against.

## suvr.py

| Flag | Meaning |
|---|---|
| `--compound neuraceq\|amyvid` | Force tracer instead of inferring from scan date |
| `--single-subject <id>` | One subject |
| `-v` | Verbose |

Pure Python (`nibabel`, `numpy`, `pandas`) — no FreeSurfer or FSL needed.

- **Reference:** whole cerebellum (labels 7, 8, 46, 47), volume-weighted; GM variant (8, 47).
- **Global:** volume-weighted pool of anterior cingulate, posterior cingulate, frontal, temporal,
  parietal — 34 Desikan–Killiany parcels.
- **Centiloid:** Amyvid `183.07 × Global − 177.26`; Neuraceq `153.4 × Global − 154.9`.
- **Tracer:** scan date ≥ 2016-09-27 → Neuraceq, else Amyvid.

> ⚠️ Per-subject tracer exceptions are **not** implemented. Subjects who received the non-default
> tracer for their date get the wrong Centiloid equation — run those with an explicit `--compound`.
> The 2016-09-27 cutoff is specific to our sites.

Headline output: `res/<combo>_suvr_combined_cerebellum.csv` — PID, Compound, Centiloid, and 21
regional SUVRs.
