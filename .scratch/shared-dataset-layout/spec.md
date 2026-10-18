# Spec: One shared Dataset Layout for the ADRC tree

Status: ready-for-agent

## Problem Statement

Every stage of the pipeline works out the ADRC tree for itself: which folders are Subjects, which are Sessions, where a Session's MRI and PET are, where its recon-all output lives, how to read a scan's name, and which MRI a PET is paired with. These rules have been written separately in a dozen places, and the copies disagree.

- Some stages count `logs/` or `fs_logs/` as a Subject.
- Some stages miss CorMPRAGE scans or PET variants such as `_PET_128`.
- The same scan name is read differently in different stages.
- The prepare step picks an MRI for each PET one way. The directory-stats tools predict the choice a different way.
- The three production SUVR scripts each carry an identical copy of the scan-name parser.
- One of the SUVR scripts has a code path that crashes because a lookup returns a generator instead of a list.
- PETs are paired with an MRI however far apart the dates are, even years apart.
- A Session that breaks the data rules is quietly processed with whichever file happened to be found first.

When something goes wrong, the maintainer has to find which of the copies was responsible. A fix in one place does not reach the others.

The directory-stats tools import the unfinished `dev/` refactors, which were never meant to be used. They do this through a fragile import-path workaround.

## Solution

A small shared Python package, `cate`, is the single authority on the ADRC tree. It is installed once into the environment, including the Docker image, and every stage imports it from wherever it runs. It answers the following questions in one consistent way:
- which Subjects and Sessions exist;
- each Session's MRI, PET and recon folder;
- how scan names and Pair folder names are read and built;
- which MRI each PET is paired with, if any;
- which Sessions break the data rules, and why.

The production SUVR scripts, the recon runner and the directory-stats tools ask `cate` for these answers instead of walking the tree themselves. The SUVR results do not change for any Session that follows the data rules.

Pairing gains a one-year limit. A PET is paired with the Subject's closest MRI within 365 days. Before any processing starts, the prepare step lists the PETs that have no MRI within a year and asks once whether to process them anyway. The answer defaults to no.

## User Stories

1. As a pipeline maintainer, I want one package that defines the ADRC tree layout, so that a rule fixed once is fixed in every stage.
2. As a pipeline maintainer, I want to install that package once into my environment, so that every stage script can import it no matter which directory it is run from.
3. As a pipeline maintainer, I want the Docker image to include the package, so that stages running in the container use the same rules as stages run on the host.
4. As a pipeline maintainer, I want the package to work on the Python version in the Docker image (3.10), so that it never crashes inside the container.
5. As a pipeline operator, I want `logs/`, `fs_logs/` and hidden folders never to be treated as Subjects, so that runs do not log spurious "subject" failures.
6. As a pipeline operator, I want only folders named with exactly eight digits (`YYYYMMDD`) to count as Sessions, so that stray folders are ignored rather than processed.
7. As a pipeline operator, I want each Session to report its MRI (T1w, or CorMPRAGE when there is no T1w), so that stages stop guessing with their own file patterns.
8. As a pipeline operator, I want each Session to report its PET whatever its variant suffix (`_PET`, `_PET_256`, `_PET_128a`, …), so that no PET is missed.
9. As a pipeline operator, I want each Session to report where its recon-all output lives, so that the path is worked out in one place.
10. As a pipeline operator, I want a Session that has an MRI but no PET to still be reported with its MRI, so that recon-all still runs for it.
11. As a pipeline operator, I want a Session that has a PET but no MRI to still be reported with its PET, so that the PET can be paired with an MRI from another Session.
12. As a pipeline operator, I want a Session holding two MRIs or two PETs to be skipped and reported as a problem, so that no file is chosen silently.
13. As a pipeline operator, I want a scan whose filename date does not match its Session folder to be reported as a problem and skipped, so that copies left by older ingest runs are never processed as the wrong Session.
14. As a pipeline operator, I want a scan whose name cannot be parsed to be reported as a problem and skipped, so that a bad name does not crash the run.
15. As a pipeline operator, I want one list of every problem in the dataset, each with its reason, so that I can fix the data by hand.
16. As a pipeline operator, I want every PET paired with the Subject's closest-dated MRI from any Session, so that PETs and MRIs taken on different days still form Pairs.
17. As a pipeline operator, I want a PET to be paired only when the MRI is 365 days or fewer away, so that scans taken years apart are not combined by accident.
18. As a pipeline operator, I want a PET whose two closest MRIs are equally far away to be reported as a problem and skipped, so that a data error is never resolved by folder order.
19. As a pipeline operator, I want a PET to have no Pair when its Subject has no MRI at all, so that it is clearly marked as waiting for an MRI.
20. As a pipeline operator, I want the prepare step to list every PET whose closest MRI is more than 365 days away before any processing starts, showing the Subject, PET date, closest MRI date and gap in days, so that I can decide with all the facts.
21. As a pipeline operator, I want to be asked once for the whole list whether to process those PETs anyway, with no as the default, so that a long run is not interrupted by many questions.
22. As a pipeline operator, I want those PETs to be skipped and listed in the log when no one is at the terminal (nohup, Docker without a terminal), so that unattended runs never hang waiting for an answer.
23. As a pipeline operator, I want a flag that approves the over-one-year PETs in advance, so that I can include them in an unattended run on purpose.
24. As a pipeline operator, I want existing Pair folders never to be deleted or rebuilt because of the new one-year rule, so that past results stay intact.
25. As a pipeline operator, I want the register and quantify steps to keep processing whatever Pair folders already exist, so that their behaviour does not change.
26. As a pipeline operator, I want the command-line options of the three SUVR scripts and the recon runner to stay the same, apart from the new approval flag, so that my existing commands and notes keep working.
27. As a pipeline operator, I want the recon runner to find MRIs through the shared layout, so that it uses exactly the same MRIs as the SUVR scripts.
28. As a pipeline operator, I want the directory-stats tools to use the same pairing rule as the prepare step, so that "missing SUVR" reports only list Pairs that prepare would actually build.
29. As a pipeline operator, I want a new `no_mri_within_year` status in the directory-stats reports, so that PETs blocked by the one-year rule are visible and not reported as missing work.
30. As a pipeline operator, I want the directory-stats tools to list existing Pair folders whose PET and MRI are more than 365 days apart, so that I can review results made before the rule existed.
31. As a pipeline maintainer, I want the directory-stats tools to stop importing layout and naming code from the unfinished `dev/` folders, so that production does not depend on unfinished code.
32. As a pipeline maintainer, I want the scan-name parser and the Pair-folder name builder to exist exactly once, so that every stage reads names the same way.
33. As a pipeline maintainer, I want the old duplicated parsers and folder-walking helpers deleted once nothing uses them, so that no one fixes a copy that is no longer used.
34. As a pipeline operator, I want the SUVR results for a Session that follows the data rules to be identical before and after this change, so that I can trust the change in production.
35. As a pipeline maintainer, I want the READMEs and `docs/` to describe the real pairing rule (closest MRI within 365 days, not a PET × MRI cross-product), so that new lab members learn the right rule.
36. As a pipeline maintainer, I want automated tests for every layout and pairing rule that run on any machine without FreeSurfer or FSL, so that I can check changes on my laptop.

## Implementation Decisions

**The `cate` package**
- A new Python package named `cate` at the repository root, with packaging metadata. It is installed in editable mode, locally and in the Docker image.
- This replaces the import-path workarounds in the directory-stats tools.
- It targets Python 3.10, so no 3.11-only features such as `StrEnum`.
- It has two modules: **names** and **layout**.

**The names module** (pure functions, no filesystem access)
- Parses a scan name `<subject>-<YYYYMMDD>_<type>[_<extra>].nii` into subject, date, scan type and optional extra. A date that is not eight valid digits is a parse error.
- Builds the standard scan filename from those parts.
- Parses and builds Pair folder names and PET output folder names. The format stays exactly as it is today, so existing folders keep their names.

**The layout module, organized around the Session**
- A **Dataset** is opened on an ADRC root folder.
- It lists **Subjects**: every folder except `logs`, `fs_logs` and hidden folders.
- Each Subject lists **Sessions**: subfolders named with exactly eight digits.
- A Session exposes:
  - its date;
  - its **MRI**: the single T1w or CorMPRAGE scan in its `anat` folder, or none;
  - its **PET**: the single `_PET*` scan in its `pet` folder, any variant suffix, or none;
  - the **recon folder** for its MRI: `freesurfer741/<MRI scan name without extension>` under the Session.
- Only `.nii` files are considered.
- `freesurfer741` is defined once in the package.

**Problems**
- A Session that breaks a data rule is excluded from what the layout reports, and is recorded as a **problem** with a reason. The rules are:
  - at most one MRI per Session;
  - at most one PET per Session;
  - every scan name parses;
  - the date in each scan name equals its Session folder's date.
- The Dataset exposes the full list of problems.
- Stages log problems but are never stopped by them.

**Pairing**
- Pairing is a decision of the layout, over a Subject's valid Sessions.
- Each PET is matched with the Subject's MRI whose date is closest to the PET's date, from any Session.
- The result for each PET is one of:
  - a **Pair**, if the closest MRI is 365 days away or less;
  - **over one year**, if the closest MRI is more than 365 days away. The closest MRI and the gap are included, so the prepare step can ask about it.
  - **no MRI**, if the Subject has no valid MRI;
  - a **problem** (tie), if two MRIs are equally close.
- Two MRIs can never legitimately be equally close, so the tie case is a data error, not a rule that picks one.
- A Pair knows:
  - its PET and its MRI;
  - the gap in days;
  - the MRI's recon folder;
  - its Pair folder location and name, in the existing format.

**Prepare step** (the production `prepare` script)
- Discovery, filename parsing, closest-MRI selection, recon path arithmetic and Pair folder naming all come from `cate`.
- Before starting any parallel work, it computes all pairing results. It then handles the over-one-year PETs:
  - If there are any and the terminal is interactive, it prints them in one table and asks once, `Process these anyway? [y/N]`.
  - Answering yes includes them as Pairs.
  - If there is no interactive terminal, they are skipped and listed in the log.
  - A new flag, `--include-over-year`, approves them without asking.
- Existing Pair folders are never deleted.
- All other command-line options are unchanged.

**Register and quantify steps** (the production `registration` and `suvr` scripts)
- They find existing Pair folders, and read scan and Pair folder names, through `cate`.
- Their processing of the Pair folders they find is unchanged. Their command-line options are unchanged.
- The `register_scan` lookup that crashes in the quantify step goes away, because the layout returns lists.

**Recon runner** (the production `mri_processing` script)
- It gets the MRIs to run recon-all on from the layout, meaning one MRI per valid Session, instead of searching for every `.nii` under `anat`.
- Recon commands and options are unchanged.

**Directory-stats tools**
- Their layout and naming imports point to `cate` instead of `dev/`.
- They use the same pairing result as the prepare step.
- PETs with no MRI within one year get the new status `no_mri_within_year`, which is reported only.
- They also report existing Pair folders whose gap is over 365 days.
- Their use of the `dev/` FreeSurfer launcher to start recon-all is unchanged in this spec.

**Contract step**
- Once every stage in scope uses `cate`, the duplicated parsers and folder-walking helpers in those stages are deleted.

**Docker image**
- Copies the package and installs it.

## Testing Decisions

- **One seam: the public interface of the `cate` package.** Tests build a small fake ADRC tree of empty files in a temporary directory. They then check only what `cate` reports: Subjects, Sessions, each Session's MRI, PET and recon folder, problems, pairing results, and name parsing and building. Tests never reach into internal helpers. They must survive internal refactors.
- Tests run with `pytest` from a top-level `tests` folder, on any operating system, with no FreeSurfer, FSL or real images.
- Every rule gets at least one test:
  - `logs` and `fs_logs` are excluded;
  - non-date folders are ignored;
  - a Session with only an MRI is valid, and so is one with only a PET;
  - CorMPRAGE is used when there is no T1w;
  - PET variant suffixes are recognized;
  - two MRIs in one Session is a problem, and so is two PETs;
  - a wrong-date scan is a problem, and so is a bad name;
  - a PET is paired across Sessions;
  - a gap of exactly 365 days is still paired, and 366 days is over one year;
  - a Subject with no MRI gives "no MRI";
  - an equal-distance tie is a problem;
  - Pair folder names keep the existing format;
  - names survive a round trip from parse to build and back.
- **Prior art**: the `Dataset`/`Subject` discovery tests and the scan-name tests in the unfinished `dev/OOP` SUVR refactor already build temporary trees of empty files. They are a reference for style only and are not used as-is.
- **Not tested automatically**:
  - the production scripts' command-line behaviour;
  - the yes/no prompt and the check for an interactive terminal;
  - the scripts' calls to external tools.

  These are covered by the manual safety check (see Further Notes).

## Out of Scope

- The unfinished `dev/` folders (the OOP SUVR refactor and the split FreeSurfer runner). They are a reference only and are not edited, promoted or deleted.
- The other stages:
  - the extract tools;
  - QC scripts;
  - aggregation and reports;
  - the symlink farm builders;
  - their own filename parsers and locators.
  They move onto `cate` in a later spec.
- A shared "is this recon or Pair complete?" status module. This includes a skip-if-done check for the recon runner.
- Wrapping FreeSurfer and FSL in swappable tool modules. The duplicated tool defaults stay as they are.
- Retiring the production SUVR scripts in favour of a rewrite.
- Changing the SUVR or Centiloid calculations, registration parameters, or the tracer cutoff.
- Changing how already-built Pair folders are named, or deleting existing Pair folders over one year.
- Ingest. Per-Session scan selection and JSON sidecars were already done separately. The MRI and PET ingest scripts deliberately stay separate.

## Further Notes

- **Safety check (manual).** Before the scripts are changed, run the prepare, register and quantify steps and the recon runner against a copy of the de-identified test dataset on the processing server, and record:
  - which Pair folders and files they create;
  - which external tool commands they issue;
  - which Pair folders the register and quantify steps pick up.

  Repeat after the change and compare. The only allowed differences are the agreed rule changes:
  - `logs`/`fs_logs` are no longer Subjects;
  - problem Sessions are skipped;
  - the one-year limit applies.

  The SUVR outputs for valid Sessions must be identical.
- Domain terms follow `GLOSSARY.md`: Delivery, Session, Session token, Pair. A Session holds at most one MRI and one PET. A PET with no MRI within one year has no Pair unless someone explicitly approves it.
- The one-year limit is 365 days, inclusive.
- The test dataset is not in git. It lives on the processing server and in local copies.
