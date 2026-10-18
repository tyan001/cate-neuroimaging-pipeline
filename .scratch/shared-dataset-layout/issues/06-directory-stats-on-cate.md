# 06: The directory-stats tools use `cate`

**What to build:** The directory-stats tools (inventory, find-missing, process-missing, merge-batch) take layout, naming and Pairing from `cate` instead of the unfinished `dev/OOP` code. Their predictions now match what the prepare step builds.

- Layout and naming imports point to `cate`, and the import-path workaround for `dev/OOP` is removed. The tools' use of the `dev/` FreeSurfer launcher to start recon-all is left as it is (out of scope).
- PET status uses `cate`'s Pairing result. A new status, `no_mri_within_year`, is reported only, never processed. The existing waiting/no-SUVR/complete statuses follow the same Pairing.
- Existing Pair folders whose PET–MRI gap is over 365 days are listed in the report.
- No 3.11-only features in the touched code: replace `StrEnum` so it runs on Python 3.10.
- The tools' README documents the new status and the over-one-year report.

**Blocked by:** 02 (The `cate` package)

**Status:** ready-for-agent

- [ ] No imports from `dev/OOP` remain in the directory-stats tools
- [ ] `no_mri_within_year` status exists, and is reported but never processed
- [ ] Predicted Pairs match `cate`'s Pairing, the same rule the prepare step uses
- [ ] Existing Pair folders over 365 days are reported
- [ ] Runs on Python 3.10
- [ ] README updated
