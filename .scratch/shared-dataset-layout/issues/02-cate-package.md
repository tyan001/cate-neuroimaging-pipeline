# 02: The `cate` package: names, Session layout, problems and Pairing

**What to build:** A shared, installable `cate` package. It is the single authority on the ADRC tree, fully tested on fake trees, and no production script uses it yet. See the spec (`../spec.md`) for the complete rules. For a real, fully processed batch to model fake trees on, see `examples/processed_batch_tree.txt`.

- **Install.** `pip install -e .` from the repo root makes `cate` importable from any directory. The Docker image copies and installs it. It works on Python 3.10, so no 3.11-only features.
- **Names.** Parse and build scan names `<subject>-<YYYYMMDD>_<type>[_<extra>].nii`. A date that is not eight valid digits is a parse error. Parse and build Pair folder names and PET output folder names in exactly today's format, so existing folders still match.
- **Layout.** Open a Dataset on an ADRC root.
  - Subjects are every folder except `logs`, `fs_logs` and hidden folders.
  - Sessions are folders named with exactly eight digits.
  - Each Session gives its date, its MRI (T1w, or CorMPRAGE when there is no T1w), its PET (any `_PET*` variant) and its recon folder.
  - Only `.nii` files count.
  - The recon folder name `freesurfer741` is defined once.
- **Problems.** A Session is excluded and recorded as a problem, with a reason, when it has two MRIs, two PETs, a scan whose name does not parse, or a scan whose name date differs from its Session folder. The Dataset lists all problems.
- **Pairing.** Each PET is compared against the Subject's valid MRIs from any Session. Each PET gets exactly one result:
  - a **Pair**, when the closest MRI is 365 days away or less (inclusive);
  - **over one year**, carrying the closest MRI and the gap;
  - **no MRI**;
  - a **tie problem**, when two MRIs are equally close.

  A Pair knows its PET, MRI, gap in days, recon folder, and Pair folder location and name.
- **Existing Pair folders.** A Subject can list its existing Pair folders on disk, with the PET date, MRI date and gap read from their names.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [x] `pip install -e .` works, and `import cate` succeeds from outside the repo
- [ ] Docker image installs the package (Dockerfile step added; image not built yet)
- [x] No Python 3.11-only features used
- [x] `pytest` runs from a top-level `tests` folder on any OS, with no FreeSurfer, FSL or real images; tests build temporary trees of empty files
- [x] Tests go through the public interface only, covering:
  - [x] `logs` and `fs_logs` excluded; non-date folders ignored
  - [x] MRI-only Session is valid; PET-only Session is valid; a Session holding both MRI and PET is valid and pairs with itself (gap 0)
  - [x] A PET pairs with a closer MRI dated after it, from another Session
  - [x] A Subject's own `logs/` folder (beside its Sessions) is ignored
  - [x] CorMPRAGE used when there is no T1w; PET variant suffixes recognized
  - [x] two MRIs, two PETs, wrong-date scan and bad name each reported as a problem
  - [x] Pairing across Sessions; 365 days pairs; 366 days is over one year
  - [x] No MRI result; tie reported as a problem
  - [x] Pair folder names identical to today's format; names survive a round trip from parse to build
  - [x] Existing Pair folders listed with their gap
- [x] Nothing in the unfinished `dev/` folders is imported or edited

## Comments

**2026-10-18, implementation.** `cate/names.py` and `cate/layout.py`, with 75 tests in `tests/`, passing on Python 3.9 and 3.10. `requires-python` is `>=3.9` because the README already promises 3.9+. The Docker step (`COPY` to `/opt/cate`, `pip3 install -e`) was checked with pip 22.0.2 on 3.10, the versions jammy ships, but the image itself was not built.

Choices the spec left open:
- An eight-digit folder that is not a real date (e.g. `20251399`) is reported as a problem, not silently ignored.
- A tie is a problem even when both MRIs are over a year away. It is checked before the one-year limit.
- `existing_pair_folders()` lists Pair folders under problem Sessions too, so no existing result is hidden.
- A Session with both T1w and CorMPRAGE uses the T1w; this is not a problem.
- As today, a PET type without an underscore (`_PET128a`) gets a PET folder named `_PET`. The variant text is lost, exactly as `create_suvr_structure()` does now.
- Subject IDs containing `_` do not parse, so Pair folder names can always be read back.
