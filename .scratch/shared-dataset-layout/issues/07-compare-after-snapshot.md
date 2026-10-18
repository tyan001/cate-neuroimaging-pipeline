# 07: Compare the "after" snapshot on the processing server

**What to build:** Proof that switching to `cate` changed nothing except the agreed rules. Repeat ticket 01's exact commands on a fresh copy of the test dataset with the updated scripts, then compare with the "before" snapshot.

Allowed differences:
- `logs` / `fs_logs` are no longer processed as Subjects;
- problem Sessions (two MRIs or PETs, wrong date, bad name, tie) are skipped and logged;
- PETs with no MRI within 365 days are not paired unless approved (run non-interactively to check they're skipped, then with `--include-over-year` to check they're included);
- the quantify step's `register_scan` fallback no longer crashes.

Any other difference is a bug, to be fixed before merging.

**Blocked by:** 03 (prepare step), 04 (register and quantify), 05 (recon runner)

**Status:** ready-for-human

- [ ] Same commands as ticket 01, on a fresh copy of the test dataset
- [ ] File/folder listings match apart from the allowed differences
- [ ] Tool commands match for valid Sessions
- [ ] Register and quantify pick up the same Pair folders
- [ ] SUVR/Centiloid outputs for valid Sessions are byte-identical
- [ ] Over-one-year behaviour checked both without a terminal and with `--include-over-year`
