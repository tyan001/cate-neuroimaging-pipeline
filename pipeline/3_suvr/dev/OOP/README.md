# OOP SUVR pipeline — how it works

The `suvr_pipeline` package runs stage 3 of the CATE pipeline: it pairs each amyloid PET scan
with an MRI, registers the PET into that MRI's space, and computes regional SUVR and Centiloid
values. You run it through [`run_suvr.py`](run_suvr.py). It produces the same folders and files as
the older `prepare_suvr_folder.py` → `registration.py` → `suvr.py` scripts.

```bash
cd pipeline/3_suvr/OOP
python3 run_suvr.py all /path/to/ADRC --cores 8             # prepare → register → quantify
python3 run_suvr.py quantify /path/to/ADRC --subject 900004  # one step, one subject
python3 -m unittest test_suvr_pipeline                        # unit tests (no data needed)
```

Requires Python 3.12 with `nibabel`, `numpy`, `pandas` and `tqdm`. The `prepare` step needs
FreeSurfer 7 (`$FREESURFER_HOME`) and `register` needs FSL (`$FSLDIR`). `quantify` is pure Python.

### Files in this folder

```
pipeline/3_suvr/
├── FreesurferLUTR.txt          ROI lookup table (shared with the original suvr.py)
├── prepare_suvr_folder.py      ┐
├── registration.py             ├ original scripts, unchanged
├── suvr.py                     ┘
└── OOP/
    ├── README.md               this file
    ├── run_suvr.py             command-line entry point
    ├── test_suvr_pipeline.py   unit tests
    └── suvr_pipeline/
        ├── naming.py           ScanFile
        ├── layout.py           Dataset, Subject, PetMriPair, PairFolder
        ├── tools.py            ExternalTool, FreeSurfer, Flirt
        ├── tracer.py           Tracer, TracerPolicy
        ├── quantify.py         RoiTable, VolumeTables, SuvrCalculator, ResultWriter
        ├── stages.py           Stage, PrepareStage, RegisterStage, QuantifyStage
        └── runner.py           StageRunner
```

Run `run_suvr.py` and the tests from inside `OOP/`, because Python finds `suvr_pipeline` relative
to the current folder. `FreesurferLUTR.txt` is looked up next to `run_suvr.py` first, then one
level up in `3_suvr/`; `--lut PATH` overrides both.

---

## 1. The big picture

```
                 run_suvr.py  (parses the command line, chooses the steps)
                      │
                      ▼
 Dataset(root) ──► [Subject, Subject, …]
                      │
                      ▼  for each step, in order
 ┌──────────────────────────────────────────────────────────────────────┐
 │ StageRunner.run(stage, subjects)                                     │
 │   1. tasks = stage.tasks(subject)  for every subject                 │
 │   2. outcome = stage.run(task)     for every task (serial or a pool) │
 │   3. summarise: done / skipped / failed                              │
 └──────────────────────────────────────────────────────────────────────┘
                      │
     PrepareStage   ──── task = PetMriPair  ─► builds the pair folder
     RegisterStage  ──── task = PairFolder  ─► FLIRT: PET → T1 space
     QuantifyStage  ──── task = PairFolder  ─► SUV → SUVR → Centiloid
```

Three ideas shape the design:

1. **A task is one PET×MRI pair.** Each step turns subjects into a flat list of pairs, and any
   worker can process any pair. Parallelism is therefore per pair, not per subject, so one subject
   with many scans doesn't hold up a worker.
2. **Steps can be re-run safely.** Each step checks what already exists and does only the missing
   work. After an interrupted run, just run the same command again.
3. **The filesystem is the only state.** Steps don't pass objects to one another. `prepare` writes
   folders; `register` and `quantify` find them again by scanning the disk. That's why each step
   also works on its own, including on folders made by the old scripts.

---

## 2. The data tree

`layout.py` models this directory structure:

```
<root>/                                            Dataset
└── 110015/                                        Subject
    ├── 20150601/anat/110015-20150601_T1w.nii      source MRI  (ScanFile)
    ├── 20150601/freesurfer741/110015-20150601_T1w/ recon-all output (from stage 2)
    │   ├── mri/{T1.mgz, aparc+aseg.mgz}
    │   └── stats/
    ├── 20150527/pet/110015-20150527_PET_128.nii   source PET  (ScanFile)
    ├── 20150527/suvr/                             ← written by this package
    │   ├── logs/                                  prepare logs
    │   └── 110015-20150527_PET_128/               PET output dir (what the symlink farm links)
    │       ├── logs/                              register logs
    │       └── 110015_pet_20150527_128_mri_20150601/     PairFolder
    │           ├── MRI/
    │           │   ├── 110015-20150601_T1w.nii                 T1 (from T1.mgz, RAS)
    │           │   ├── 110015-20150601_T1w_aparc+aseg.nii      labels (RAS)
    │           │   ├── 110015-20150601_T1w_asegVolume.csv
    │           │   ├── 110015-20150601_T1w_aparcstatsVolumLeft.csv
    │           │   ├── 110015-20150601_T1w_aparcstatsVolumRight.csv
    │           │   └── 110015-20150527_PET_128.nii             copy of the source PET
    │           ├── register_scan/
    │           │   ├── 110015-20150527_128_reg_110015-20150601_T1w.nii
    │           │   └── 110015-20150527_128_reg_110015-20150601_T1w.mat
    │           └── res/                           11 result files (see §5)
    └── logs/                                      quantify logs
```

### Filenames carry the metadata — `naming.ScanFile`

Every scan is named `<subject>-<YYYYMMDD>_<modality>[_<extra>].nii`. `ScanFile.parse(path)`
splits the name into its fields:

| Filename | subject_id | date | modality | extra |
|---|---|---|---|---|
| `900004-20150527_PET.nii` | 900004 | 20150527 | PET | – |
| `110015-20150527_PET_128.nii` | 110015 | 20150527 | PET | 128 |
| `900041-20200224_CorMPRAGE.nii` | 900041 | 20200224 | CorMPRAGE | – |

`ScanFile.parse` raises `ValueError` on a malformed name. During discovery, files with malformed
names are logged and skipped rather than failing the whole subject. `with_extra(prefix)` appends
`_<extra>` when the scan has one; every derived folder and file name is built with it.

### Two views of a pair

| Class | Represents | Built from | Used by |
|---|---|---|---|
| `PetMriPair` | A pair that *should* exist | Source scans (`Subject.pairs()`) | `prepare` |
| `PairFolder` | A pair folder that *does* exist | Disk (`Subject.pair_folders()`) | `register`, `quantify` |

`PetMriPair` works out where everything goes: `suvr_dir`, `pet_output_dir`, `pair_dir_name`,
`freesurfer_subject_dir`. Its `.folder` property returns the matching `PairFolder`.

`PairFolder` finds what's inside a pair folder: `t1_images()`, `source_pets()`, `aparc_aseg()`,
`registered_pets()`, and `scan_date()`. `scan_date()` reads the date from the registered PET's
name, or from the folder name if that fails. All lookups are sorted, so results are deterministic,
and they ignore `*.partial.*` files left behind by interrupted runs.

### Pairing rule — `Subject.pairs()` and `closest_mri()`

Each PET scan is paired with the **single MRI closest in date**, measured as `|MRI date − PET date|`
in days. If two MRIs are equally close, the one that comes first in sorted path order wins. MRIs
are found in any `anat/` folder under the subject, matching `*T1w*.nii` or `*CorMPRAGE*.nii`.
PET scans are `<session>/pet/*.nii` files whose names contain `_PET`.

Folders made by the old scripts may hold several MRI pairs per PET scan (the old pairing used
every PET×MRI combination). `pair_folders()` returns whatever is on disk, so `register` and
`quantify` still process those folders.

---

## 3. The three steps — `stages.py`

Every step subclasses `Stage` and implements three methods:

```python
class Stage(ABC):
    name: ClassVar[str]
    def tasks(self, subject) -> list: ...          # what to do for this subject
    def log_file(self, task) -> Path: ...          # where this task's log goes
    def process(self, task, log) -> Status: ...    # do it; return DONE/SKIPPED, or raise

    def run(self, task) -> Outcome: ...            # provided: logging + error capture
```

`Stage.run()` is what worker processes call. It opens the task's log file, calls `process()`,
and turns any exception into an `Outcome(status=FAILED, message=...)`, so `run()` itself never
raises. To fail a task with a clear message, `process()` raises `StageError`.

### `PrepareStage` — build the pair folder

Task: `PetMriPair`. Uses a `FreeSurfer` tool object.

1. Checks that `freesurfer741/<mri stem>/mri/` exists. If it doesn't, the task fails with
   "has recon-all run?" and nothing is created.
2. Creates `MRI/`, `res/` and `register_scan/`.
3. Converts `T1.mgz` and `aparc+aseg.mgz` to NIfTI with `mri_convert --out_orientation RAS`.
   Both get the **same** orientation, so the label volume and the registered PET share a voxel
   grid, and `quantify` can match voxels directly.
4. Writes the three volume CSVs. If recon-all already left a precomputed table in `stats/`, it is
   copied with tabs changed to commas; otherwise it is generated with
   `aparcstats2table` / `asegstats2table` (with `SUBJECTS_DIR` set to `freesurfer741/`).
5. Copies the source PET into `MRI/`.

Each sub-step runs only if its output file is missing. The step returns `DONE` if it wrote
anything and `SKIPPED` if everything was already there.

### `RegisterStage` — PET into T1 space

Task: `PairFolder`. Uses a `Flirt` tool object.

For each T1 × PET found in `MRI/` (normally one of each), it runs:

```
flirt -in PET -ref T1 -out register_scan/<pet>_reg_<mri>.nii -omat ….mat
      -bins 256 -cost corratio -searchr{x,y,z} -90 90 -dof 12 -interp trilinear
```

The step skips the pair if the output `.nii` already exists. Delete that file to force a new
registration. The FLIRT settings are fields on `Flirt` (`dof`, `cost`, `bins`, `search_range`,
`interp`) and match the settings the published results were validated against.

### `QuantifyStage` — SUVR and Centiloid

Task: `PairFolder`. Holds a `TracerPolicy` and the path to the lookup table.

1. Finds the registered PET: the first in sorted order, with a warning if there are several.
2. Finds `*_aparc+aseg.nii` and the three volume CSVs (`VolumeTables.load`).
3. Gets the PET date and picks the tracer with `TracerPolicy.for_date`.
4. Runs `SuvrCalculator.compute_files` → `SuvrResult`, then `ResultWriter.write`.
5. **Sanity check:** if the cerebellum reference SUV is ≤ 0, the files are still written but the
   task **fails**. Every SUVR in those files is 0 and the Centiloid is just −intercept, which
   looks like a real number downstream.

`quantify` always recalculates. It takes a few seconds per pair and never overwrites anything
that took real computing time to produce.

The lookup table is loaded once per process and cached in `QuantifyStage.rois`.
`__getstate__` drops the cached copy when the stage is sent to worker processes, so each worker
loads its own copy instead of receiving it pickled with every task.

---

## 4. External tools — `tools.py`

```
ExternalTool            env() + run(cmd, log, extra_env) → raises ToolError on failure
├── FreeSurfer(home)    convert(src, dst) · stats_table(cmd, subjects_dir, dst)
└── Flirt(fsl_dir, …)   register(moving, reference, out)
```

- Each subclass sets up its own environment variables. `FreeSurfer` checks that
  `FREESURFER_HOME` exists; `Flirt` sets `FSLDIR`, adds `$FSLDIR/bin` to `PATH` and sets
  `FSLOUTPUTTYPE=NIFTI`.
- **Outputs are only ever complete.** Every tool writes to `partial_path(dst)`
  (`foo.nii` → `foo.partial.nii`) and renames the file into place when it finishes. `Flirt`
  moves the `.mat` file first and the `.nii` last, because the `.nii` is what the skip check
  looks for. A process killed mid-write therefore leaves only a `.partial` file, which discovery
  ignores and the next run replaces.
- A failure raises `ToolError` with the tool's stderr, and that message appears in the run summary.

For tests, pass in a stand-in: `PrepareStage(freesurfer=mock.Mock())`.

---

## 5. The calculation — `quantify.py` and `tracer.py`

### Lookup tables

- **`RoiTable`** wraps `3_suvr/FreesurferLUTR.txt`: 116 rows mapping label → name. It has 44
  non-cortical labels (label < 1000; 0 is `Unknown`), 35 left-cortex labels (1000–1999) and
  35 right-cortex labels (2000+). Its row order is the row order of every per-ROI output file.
- **`VolumeTables`** holds the three CSVs made by `prepare`. `aseg(column)` looks up a
  subcortical volume by exact column name and raises an error if it's missing.
  `for_label(label, rois)` works for any label:

  | Label | Table | Column |
  |---|---|---|
  | < 1000 | aseg | name with spaces → `-` |
  | 1000–1999 | aparc left | `lh_<name minus "ctx-lh-">_volume` |
  | ≥ 2000 | aparc right | `rh_<name minus "ctx-rh-">_volume` |

  If a column is missing, `for_label` returns 0.0, so that parcel gets no weight, and logs a
  warning. The exception is corpus callosum (1004/2004): FreeSurfer's DK atlas never has it, so
  that message is logged at debug level only.

### `SuvrCalculator.compute(pet, aparc, volumes)` → `SuvrResult`

```
mask   = aparc != 0                        voxels with a label
for each LUT label:
    vals = PET voxels with that label
    suv_mean / suv_median / suv_sum[label] = mean / median / sum(vals)   (0 if no voxels)
min, max = over all labelled voxels

suv_cer    = volume-weighted mean of suv_mean over labels 7, 8, 46, 47   (whole cerebellum)
suv_cer_gm = volume-weighted mean over labels 8, 47                      (cerebellar cortex)
suvr       = suv_mean / suv_cer          (all zeros if suv_cer ≤ 0)
regional   = composites below
```

Composites are **volume-weighted pools**, not averages of averages. `_Pool` keeps a running
Σ(SUVR × volume) and Σ(volume):

| Output | Pooled over |
|---|---|
| `<Region>Left` / `<Region>Right` | That region's parcels in one hemisphere |
| `<Region>` | Both hemispheres' parcels together |
| `GlobalLeft` / `GlobalRight` / `Global` | All parcels of the five `GLOBAL_REGIONS` |
| `TotalLeft` / `TotalRight` / `Total` | Every cortical label in the LUT (35 + 35) |

`GLOBAL_REGIONS` lists 5 `CorticalRegion`s, with 19 Desikan–Killiany parcels per hemisphere:

| Region | Parcels per hemisphere |
|---|---|
| AnteriorCingulate | 2 (caudal + rostral anterior cingulate) |
| PosteriorCingulate | 2 (posterior + isthmus cingulate) |
| Frontal | 9 |
| Temporal | 2 |
| Parietal | 4 |

A pool with zero total volume yields 0.0, not NaN.

> **Why the code looks the way it does:** the additions and loops happen in exactly the same order
> as in `suvr.py`. Floating-point addition isn't associative, so this order is what makes the
> output **byte-identical** to the numbers already published. Don't "simplify" it into
> `np.average(..., weights=...)` without checking the result against existing output.

### Tracer and Centiloid — `tracer.py`

```python
AMYVID   = Tracer("Amyvid",   slope=183.07, intercept=177.26)   # CL = 183.07 × Global − 177.26
NEURACEQ = Tracer("Neuraceq", slope=153.4,  intercept=154.9)    # CL = 153.4  × Global − 154.9

TracerPolicy()                    # date ≥ 2016-09-27 → Neuraceq, else Amyvid
TracerPolicy.from_name("amyvid")  # --compound: same tracer for every scan
```

Per-subject exceptions are **not** built in. Run subjects who received the non-default tracer
separately, with `--subject … --compound …`.

### Output files — `ResultWriter.write`

The file prefix is the pair folder name, e.g. `900004_pet_20150527_mri_20150616`.

| File | Contents |
|---|---|
| `_max`, `_min` | Largest / smallest SUV over labelled voxels |
| `_suv_cer`, `_suv_cer_gm` | Reference SUVs (plain text, no extension) |
| `_mean_suv.csv`, `_median_suv.csv`, `_total_suv.csv` | One row per LUT label: `ROI,Name,Value` |
| `_suvr_cerebellum.csv` | Transposed: header = labels; row 1 = names; row 2 = SUVR (`PID` column first) |
| `_suvr_cerebellum_gm.csv` | Same, rescaled by `suv_cer / suv_cer_gm` (cortex-only reference) |
| `_suvr_combined_cerebellum.csv` | **Headline file**: `PID, Compound, Centiloid` + 21 composites |
| `_suvr_combined_cerebellum_gm.csv` | Same, using the cerebellar-cortex reference |

`PID` is the registered PET's filename. `5_aggregate/suvr_stats_all.py` reads these files, so
their formats must not change.

---

## 6. Running the steps — `runner.py`

`StageRunner(cores, verbose).run(stage, subjects)`:

1. **Collects tasks.** It calls `stage.tasks(subject)` for each subject. A subject whose tasks
   can't be listed (for example, an unreadable directory) is logged and skipped; the other
   subjects continue.
2. **Picks a worker count:** `min(--cores, CPUs available to this process, number of tasks)`.
   With 1 worker, tasks run in the main process, which is easiest for debugging.
3. **Runs the tasks.** With more than one worker it uses `ProcessPoolExecutor`. Each worker
   configures its own logging through `initializer=configure_logging`, so it doesn't depend on
   how Python starts worker processes. A progress bar tracks completed tasks.
4. **Summarises:** `done N, skipped N, failed N`, then one line per failure with its message.

`run_suvr.py` adds up the failures across steps and **exits with 1 if any task failed**, so it
can gate scripts or scheduled jobs.

> With `all`, `register` still runs after `prepare` even if some `prepare` tasks failed. Folders
> that didn't finish simply fail again with "run `prepare` first", so every problem shows up in
> one run.

### Logging

- **Console:** the root logger, set up in `configure_logging`, shows every task.
- **Per-task file:** `task_log()` attaches a log-file handler to the `suvr_pipeline` package
  logger for the duration of one task. It therefore also captures warnings from `layout` and
  `quantify` (for example, a missing volume column). A worker runs one task at a time, so tasks
  never write into each other's files.

| Step | Log file |
|---|---|
| prepare | `<session>/suvr/logs/suvr_setup_<PETdate>_<timestamp>.log` |
| register | `<PET output dir>/logs/pet_registration_<timestamp>.log` |
| quantify | `<subject>/logs/pet_suvr_processing_<pair folder>_<timestamp>.log` |

---

## 7. What happens on a re-run

| Step | Considered done when… | To force a re-run |
|---|---|---|
| prepare | Each of: T1 `.nii`, aparc+aseg `.nii`, 3 CSVs, PET copy exists | Delete that file |
| register | `register_scan/<…>_reg_<…>.nii` exists | Delete the `.nii` (and `.mat`) |
| quantify | Never — always recalculates | — |

---

## 8. Extending the pipeline

**Add a step.** Subclass `Stage`, then add it to `build_stages()` and the `stage` choices in
`run_suvr.py`:

```python
@dataclass
class QcStage(Stage):
    name: ClassVar[str] = "qc"

    def tasks(self, subject):  return subject.pair_folders()
    def log_file(self, folder): return folder.pet_output_dir / "logs" / f"qc_{_timestamp()}.log"
    def process(self, folder, log):
        if not folder.registered_pets():
            raise StageError("not registered")
        ...
        return Status.DONE
```

Keep tasks and stage fields picklable (plain dataclasses and paths), because they are sent to
worker processes.

**Change FLIRT settings** without touching `stages.py`:
`RegisterStage(flirt=Flirt(dof=6, cost="normmi"))`. Registrations that already exist are kept,
so write to a copy of the tree, or delete the old outputs first.

**Add a tracer:** define `Tracer(name, slope, intercept)` and add it to `TRACERS`; `--compound`
picks it up automatically. A different date cutoff is `TracerPolicy(cutoff=datetime(...))`.

**Change or add composite regions:** pass `regions=[CorticalRegion(...), ...]` to
`SuvrCalculator`. `ResultWriter` writes exactly the columns listed in `COMBINED_COLUMNS`:
a region not listed there is left out of the CSV, and a listed column with no computed value is
written as 0.0. To output a new region, add it to `COMBINED_COLUMNS` too. That changes the file
format, so check `5_aggregate` first.

**Use the pieces from Python:**

```python
from pathlib import Path
from suvr_pipeline.layout import Dataset
from suvr_pipeline.quantify import RoiTable, SuvrCalculator, VolumeTables

rois = RoiTable.load()
for folder in Dataset(Path("/mnt/backup/dev/NWSI/ADRC")).subjects(["900004"])[0].pair_folders():
    aparc = folder.aparc_aseg()
    vols = VolumeTables.load(folder.mri_dir, aparc.stem.replace("_aparc+aseg", ""))
    r = SuvrCalculator(rois).compute_files(folder.registered_pets()[0], aparc, vols)
    print(folder.name, r.regional["Global"])
```

---

## 9. Tests and checks

- `test_suvr_pipeline.py` (17 tests, standard-library `unittest`, no data or tools needed):
  filename parsing, folder and file naming (including `_PET_256` and CorMPRAGE), closest-MRI
  pairing and ties, tracer cutoff, discovery skipping `logs/` and `.partial` files, `prepare`
  finishing a half-built folder, failure without recon-all, the pooling math on a tiny synthetic
  volume, and the reference-≤-0 check.
- Checked against the old scripts on real data (2026-09-16):
  - `res/` output byte-identical on 70 pair folders;
  - a full `all` run on 900004 and 110015 (5 pairs) produced the same 95 files as
    `prepare_suvr_folder.py` → `registration.py` → `suvr.py`, byte for byte, including the
    NIfTI and `.mat` files.

After changing anything in `quantify.py`, repeat the byte comparison against existing `res/`
output before trusting new numbers.
