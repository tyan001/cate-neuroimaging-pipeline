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
| `make_suvr_symlink_farm.py` | Flat directory of symlinks to every `<subj>-<date>_PET[...]` output folder |
| `OOP/` | Object-oriented version of the three scripts above — see below and [OOP/README.md](OOP/README.md) |

---

## OOP/run_suvr.py (object-oriented pipeline)

One entry point with the same three steps as the scripts above. It writes the same folder layout
and the same file formats. `res/*` is byte-identical to `suvr.py` (checked on 70 real pair folders).

```bash
cd OOP
python3 run_suvr.py prepare  /path/to/ADRC --cores 8
python3 run_suvr.py register /path/to/ADRC --cores 8
python3 run_suvr.py quantify /path/to/ADRC --cores 4
python3 run_suvr.py all      /path/to/ADRC --cores 8                   # all three in order
python3 run_suvr.py quantify /path/to/ADRC --subject 110041 --compound amyvid
python3 -m unittest test_suvr_pipeline                                  # unit tests
```

| Flag | Meaning |
|---|---|
| `--subject ID` | Limit to a subject; repeatable |
| `--cores N` | Worker processes (default 1). Work is split per PET×MRI pair, not per subject |
| `--compound amyvid\|neuraceq` | `quantify`: force the tracer |
| `--lut PATH` | `quantify`: ROI table (default `3_suvr/FreesurferLUTR.txt`) |
| `-v` | Debug logging |

| Module | Classes |
|---|---|
| `naming.py` | `ScanFile`: parsed `<subj>-<date>_<modality>[_<extra>].nii` |
| `layout.py` | `Dataset` → `Subject` → `PetMriPair` (to build) / `PairFolder` (already on disk) |
| `tools.py` | `FreeSurfer` (`mri_convert`, `*stats2table`), `Flirt` |
| `tracer.py` | `Tracer` (Centiloid equation), `TracerPolicy` (date cutoff or override) |
| `quantify.py` | `RoiTable`, `VolumeTables`, `CorticalRegion`, `SuvrCalculator` → `SuvrResult`, `ResultWriter` |
| `stages.py` | `Stage` → `PrepareStage`, `RegisterStage`, `QuantifyStage` |
| `runner.py` | `StageRunner`: runs tasks serially or in a process pool, prints a summary |

**How it differs from the three scripts**

- **Resuming works per file.** `prepare` checks each output separately (T1, aparc+aseg, three CSVs,
  PET copy). The old script skipped any pair folder that already existed, so a run interrupted
  halfway left that folder incomplete for good. Tool outputs are written as `*.partial.*` and then
  renamed, so a killed run never leaves a half-written file that counts as done.
- **More cases count as failures.** A pair whose MRI has no `recon-all` output fails without
  creating empty folders (the old script reported these as successful). `quantify` fails if it
  can't read the PET date; the old script silently used today's date, which always means Neuraceq.
- **Invalid reference region.** When the cerebellum reference SUV is ≤ 0, `quantify` still writes
  `res/`, as before, but marks the task as failed. Those files contain all-zero SUVRs and a
  Centiloid of exactly −intercept (e.g. −177.26), which looks like a real value downstream.
- **Log files** stay where they were (`suvr/logs`, `<PET dir>/logs`, `<subject>/logs`). There is now
  one log per task, and it holds only that task's messages (the old scripts could send later
  subjects' messages to the first subject's log). `quantify` log names include the pair folder name.
- **Exit code** is nonzero if any task failed.

---

## prepare_suvr_folder.py

| Flag | Meaning |
|---|---|
| `--cores N` | Worker processes |
| `--parallel-mode subjects\|combinations` | Parallelize over subjects (default) or pairs |
| `--disable-parallel` | Serial, for debugging |
| `--single-subject <id>` | One subject |
| `-v` | Verbose |

Pairs each PET scan with its **closest-dated MRI session** for the subject (by `|MRI date − PET
date|`, ties broken deterministically) — one pair folder per PET scan, not a cross-product.

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
