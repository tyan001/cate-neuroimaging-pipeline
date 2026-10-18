# 04: The register and quantify steps use `cate`

**What to build:** The production register and quantify steps find existing Pair folders and read scan and Pair folder names through `cate`. Their processing of each Pair folder is unchanged.

- Subject listing, Session date parsing, finding a Subject's existing Pair folders, and reading dates from scan and Pair folder names all come from `cate`.
- Both scripts' copies of the filename parser and their own folder walkers are deleted.
- `logs` and `fs_logs` are no longer processed as Subjects.
- The quantify step's fallback lookup of the `register_scan` folder no longer crashes. It used to treat a generator as a list; it now gets a real list, or a clear "not found" log entry.
- Registration parameters, SUVR/Centiloid maths, tracer selection, outputs and command-line options are unchanged.

**Blocked by:** 01 (Record the "before" snapshot), 02 (The `cate` package)

**Status:** ready-for-agent

- [ ] Both steps import `cate`, and their duplicated parsers and walkers are gone
- [ ] The same Pair folders are picked up as before (excluding anything under `logs`/`fs_logs`)
- [ ] The `register_scan` fallback path returns a list or logs "not found", with no AttributeError
- [ ] Command-line options and outputs unchanged
