# Processed batch: output formats and logs

What the files in [`processed_batch_tree.txt`](processed_batch_tree.txt) contain. Taken from the same real batch and de-identified the same way: Subject IDs `990001`–`990003`, dates shifted, run timestamps shown as `<ts>`. Only headers and log lines are kept. No measured values are included.

Paths in the logs start with `data/` because the scripts ran inside the container, with the batch root mounted at `/workspace/data`.

---

## Quirks this batch shows

Today's production scripts behave this way. Check them before treating a difference in ticket 01/07 as a regression.

1. **SUVR logs leak across Subjects.** `suvr.py` writes every Subject's output into the log of the first Subject it processes (`990001`, which has no PET). The other Subjects' `pet_suvr_processing_*.log` files are created but stay at 0 bytes. `prepare_suvr_folder.py` does the same with `suvr_setup_*.log`: `990003`'s Session log holds both Pairs' setup, and `990002`'s is empty. Both scripts set up their per-Subject or per-Session log with `logging.basicConfig`, which only takes effect the first time it is called in a process. So a per-Subject log tells you nothing on its own.
2. **`mri_site_data.py` needs the symlink farm.** Run on `ADRC/`, it skipped every Subject (`not inside a freesurfer741 directory`). Run on `freesurfer_link/` with an output root, it wrote `viewer/<subj>/<session>/` instead of `sitedata_mri/` inside each Session.
3. **A Session can hold both MRI and PET.** `990002/20250519/` has `anat/`, `freesurfer741/`, `pet/`, `ct/` and `suvr/` together. This contradicts rule 3 in `docs/04-data-organization.md` ("never both").
4. **A PET can pair with a later MRI.** `990003`'s PET (`20250602`) pairs with the MRI three days later (`20250605`), which is in another Session. The Pair folder is filed under the PET's Session, and its `MRI/` files come from the MRI Session's recon.
5. **An MRI-only Subject still gets `logs/`.** `990001/logs/` exists because `suvr.py` opens a log for every Subject. So a non-date folder sits next to Sessions in every Subject, PET or not.
6. **PET sidecars are not ingested.** The PET delivery's JSON sidecars and the `_aPET_mean_3mmblur_T1_space.nii.gz` stay in `PET/` only. PET Sessions get no `modalities/`.

---

## Study tables

`mri_csv/*.csv`: one row per recon. The first four columns are shared, and the rest are FreeSurfer measures.

```
subject_id,scan_date,scan_type,subject,<measures...>
990002,20250519,T1w,990002-20250519_T1w,...
```

| File | Columns | First measures |
|---|---|---|
| `aseg_stats.csv` | 68 | `Left-Lateral-Ventricle, Left-Inf-Lat-Vent, ...` |
| `aparc_volume.csv` | 76 | `lh_bankssts_volume, lh_caudalanteriorcingulate_volume, ...` |
| `aparc_thickness.csv` | 78 | `lh_bankssts_thickness, ...` |
| `wmparc.csv` | 79 | `wm-lh-bankssts, wm-lh-caudalanteriorcingulate, ...` |
| `hippocampus.csv` | 48 | `lh_Hippocampal_tail, lh_subiculum-body, lh_CA1-body, ...` |
| `amygdala.csv` | 24 | `lh_Lateral-nucleus, lh_Basal-nucleus, ...` |

`suvr_csv/*.csv`: one row per Pair. `pet_info` and `mri_info` are empty here. They hold whatever follows the date in the Pair folder name, such as `128` in `..._pet_20240110_128_mri_...` or `CorMPRAGE` after the MRI date.

```
subject_id,pet_date,pet_info,mri_date,mri_info,PID,<...>
990002,20250519,,20250519,,990002-20250519_reg_990002-20250519_T1w.nii,...
```

| File | Columns | After `PID` |
|---|---|---|
| `suvr_cerebellum.csv`, `suvr_cerebellum_gm.csv` | 122 | one column per aparc+aseg label: `Unknown, Left-Cerebral-White-Matter, ...` |
| `suvr_combined_cerebellum.csv`, `..._gm.csv` | 29 | `Compound, Centiloid, AnteriorCingulateLeft, AnteriorCingulateRight, ...` |

`Compound` is `Neuraceq` for both PETs (Florbetaben).

---

## Pair folder files

| File | Format |
|---|---|
| `MRI/<mri>_T1w_asegVolume.csv` | `Measure:volume,Left-Lateral-Ventricle,...` (65 cols, `asegstats2table`) |
| `MRI/<mri>_T1w_aparcstatsVolum{Left,Right}.csv` | `lh.aparc.volume,lh_bankssts_volume,...` (37 cols, `aparcstats2table`) |
| `res/<pair>_{mean,median,total}_suv.csv` | `ROI,Name,Value` |
| `res/<pair>_suvr_cerebellum[_gm].csv` | `PID,0,2,4,5,7,8,10,...` (header row is label numbers) |
| `res/<pair>_suvr_combined_cerebellum[_gm].csv` | `PID,Compound,Centiloid,AnteriorCingulateLeft,...` |
| `res/<pair>_{max,min,suv_cer,suv_cer_gm}` | one bare number, no extension, no newline |

---

## Log excerpts

### Ingest: `logs/pet_bids_logs/pet_bids_batch88_<ts>.log`

```
INFO - Found 2 PET_* subfolders in Processing/Both/batch88/PET
INFO - PET patterns: mean_5mmblur, PET_6mmblur, PET_3mmblur, PET_256, PET_128
INFO - CT patterns: amyloid_pet_ct, pet_ct, amyloid_ct
INFO - Processing folder: PET_990002-C2_05192025
INFO - Parsed folder 'PET_990002-C2_05192025' to subject_id='990002', session='C2', scandate='20250519'
INFO - Found PET file for 990002: .../PET_990002-C2_05192025/990002-C2_05192025.Amyloid_PET_3mmblur.nii
INFO - Found CT file for 990002: .../PET_990002-C2_05192025/990002-C2_05192025.Amyloid_PET_CT.nii
INFO - RENAMED: ...Amyloid_PET_3mmblur.nii -> Processing/Both/batch88/ADRC/990002/20250519/pet/990002-20250519_PET.nii (PET scan)
INFO - RENAMED: ...Amyloid_PET_CT.nii -> Processing/Both/batch88/ADRC/990002/20250519/ct/990002-20250519_CT.nii (CT scan)
```

The MRI log (`mri_bids_logs/`) has the same shape: one `COPIED:` line per file into `modalities/`, then `RENAMED: ...T1.nii -> .../anat/990001-20250412_T1w.nii (used T1)`.

### Recon: `fs_logs/batch88.log`

```
mri_processing - INFO - Starting MRI processing with 4 cores
mri_processing - INFO - Found 3 .nii files for processing
mri_processing - INFO - === PROCESSING SUMMARY ===
mri_processing - INFO - FreeSurfer successful: 3/3
mri_processing - INFO - Average FreeSurfer time per subject: 17739.71 seconds
mri_processing - INFO - Hippocampus segmentation successful: 3/3
mri_processing - INFO - Average hippocampus time per subject: 1889.07 seconds
```

### Prepare: `ADRC/990003/20250602/suvr/logs/suvr_setup_20250602_<ts>.log`

The tool commands for one Pair. The same log then continues with `990002`'s Pair (quirk 1).

```
[PET:990003-20250602_PET.nii - MRI:990003-20250605_T1w.nii] Processing combination
Created directory: data/ADRC/990003/20250602/suvr/990003-20250602_PET/990003_pet_20250602_mri_20250605/MRI
Created directory: .../990003_pet_20250602_mri_20250605/res
- Running conversion command: mri_convert -ot nii --out_orientation RAS data/ADRC/990003/20250605/freesurfer741/990003-20250605_T1w/mri/T1.mgz .../MRI/990003-20250605_T1w.nii
- Running conversion command: mri_convert -ot nii --out_orientation RAS .../mri/aparc+aseg.mgz .../MRI/990003-20250605_T1w_aparc+aseg.nii
- Running FreeSurfer command: aparcstats2table --subjects 990003-20250605_T1w --hemi lh --meas volume --tablefile .../MRI/aparcstatsVolumLeft.csv
- Running FreeSurfer command: aparcstats2table --subjects 990003-20250605_T1w --hemi rh --meas volume --tablefile .../MRI/aparcstatsVolumRight.csv
- Running FreeSurfer command: asegstats2table --subjects 990003-20250605_T1w -m volume --tablefile .../MRI/asegVolume.csv
Copied 990003-20250602_PET.nii to MRI folder: .../MRI/990003-20250602_PET.nii
Created register_scan directory at: .../990003_pet_20250602_mri_20250605/register_scan
[PET:990003-20250602_PET.nii - MRI:990003-20250605_T1w.nii] Successfully created/updated SUVR structure
```

The `--tablefile` names have no prefix. The files on disk do (`990003-20250605_T1w_asegVolume.csv`), so they are renamed after they are written.

### Register: `.../990002-20250519_PET/logs/pet_registration_<ts>.log`

```
Processing registrations for directory: 990002_pet_20250519_mri_20250519
flirt -in .../MRI/990002-20250519_PET.nii -ref .../MRI/990002-20250519_T1w.nii
      -out .../register_scan/990002-20250519_reg_990002-20250519_T1w.nii
      -omat .../register_scan/990002-20250519_reg_990002-20250519_T1w.mat
      -bins 256 -cost corratio -searchrx -90 90 -searchry -90 90 -searchrz -90 90 -dof 12 -interp trilinear
Registration completed successfully
- Successful: 1
- Failed: 0
```

### Quantify: `ADRC/990001/logs/pet_suvr_processing_990001_<ts>.log`

```
Processing subject: 990001
No scan dates with SUVR folders found for 990001
Log file created at: data/ADRC/990003/logs/pet_suvr_processing_990003_<ts>.log   <- next Subject, same file
Processing subject: 990003
Found 1 scan dates with SUVR folders
Processing scan date: 20250602
Processing PET folder: 990003-20250602_PET
Processing MRI folder: 990003_pet_20250602_mri_20250605
PET file: .../register_scan/990003-20250602_reg_990003-20250605_T1w.nii
Loaded subcortical data shape: (1, 65)
Loaded cortical_left data shape: (1, 37)
Loaded cortical_right data shape: (1, 37)
Successfully processed 990003_pet_20250602_mri_20250605
...
```

### Viewer conversion: `conversion_logs/` vs `viewer/conversion_logs/`

```
Input path: /workspace/data/ADRC
Output folder name: sitedata_mri
  WARNING: skipping 990001 (/workspace/data/ADRC/990001 is not inside a freesurfer741 directory)
Found 0 subjects to process
```
```
Input path: .../Processing/Both/batch88/freesurfer_link
Output root: .../Processing/Both/batch88/viewer (<subject>/<session>/ per scan)
Found 3 subjects to process
  Converting T1.mgz to T1.nii
    Success: .../viewer/990002/20250519/mri/T1.nii
```
