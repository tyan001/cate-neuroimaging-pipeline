# 03: The prepare step uses `cate`, with the one-year question

**What to build:** The production prepare step builds Pair folders from `cate`'s Pairing instead of its own discovery. The operator decides about PETs that have no MRI within a year.

- Subjects, Sessions, scan names, closest-MRI choice, recon folder and Pair folder naming all come from `cate`. The prepare step's own copies of the filename parser, MRI finder, closest-MRI logic and recon path arithmetic are deleted.
- Problems reported by `cate` are logged and skipped, and never stop the run.
- PETs with no MRI or a tie are skipped and logged.
- Before any parallel work starts, all Pairing results are computed. Then, for PETs whose closest MRI is over 365 days away:
  - If there are any and the terminal is interactive, print one table (Subject, PET date, closest MRI date, gap in days). Ask once, `Process these anyway? [y/N]`. Enter means no.
  - With no interactive terminal, they are skipped and listed in the log.
  - A new `--include-over-year` flag approves them without asking.
- Existing Pair folders are never deleted. All other command-line options and behaviour stay the same.
- READMEs and `docs/` describe the real pairing rule: the closest MRI within 365 days, not a PET × MRI cross-product.

**Blocked by:** 01 (Record the "before" snapshot), 02 (The `cate` package)

**Status:** ready-for-agent

- [ ] The prepare step imports `cate`, and its duplicated parser and discovery helpers are gone
- [ ] Pair folders created for a valid Pair have exactly the same names and contents as before
- [ ] Over-one-year PETs are listed and asked about once; the default is no
- [ ] Non-interactive runs skip over-one-year PETs and log them; `--include-over-year` includes them
- [ ] No-MRI, tie and problem Sessions are logged and skipped
- [ ] Existing command-line options unchanged; `--include-over-year` documented in `--help` and the README
- [ ] Docs no longer describe a PET × MRI cross-product
