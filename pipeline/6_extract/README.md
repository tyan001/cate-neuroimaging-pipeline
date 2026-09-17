# 6. Extracting scans

Pull specific scans back out of the assembled dataset given subject IDs and dates — for sharing,
for a sub-study, or to feed another tool.

Dates are entered as **`MM/DD/YYYY`** and converted to the `YYYYMMDD` folder convention internally.

Set the dataset root once:

```bash
export ADRC_ROOT=/data/NWSI/ADRC
```

`scan_finder.py` and `interactive_scan_finder.py` fall back to `$ADRC_ROOT` when no path is given;
the others take it as a required flag.

| Script | Purpose |
|---|---|
| `scan_finder.py` | Library + CLI: locate one scan, or list a subject's sessions |
| `find_t1w.py` | Locate a single T1w scan |
| `find_pet.py` | Locate a single PET scan |
| `interactive_scan_finder.py` | Menu-driven wrapper around `scan_finder` |
| `batch_copy_scans.py` | Bulk copy from a CSV of subject IDs and dates |

---

## scan_finder.py

```bash
python3 scan_finder.py -f "$ADRC_ROOT" -p 110001 -d 01/15/2020 -t T1w
python3 scan_finder.py -f "$ADRC_ROOT" -p 110001 --list-dates
```

| Flag | Meaning |
|---|---|
| `-f, --folder` | Dataset root (required) |
| `-p, --patient` | Subject ID (required) |
| `-d, --date` | `MM/DD/YYYY` |
| `-t, --type` | `T1w` or `PET` |
| `--list-dates` | List all sessions for the subject |

It is also the shared library — `find_t1w_scan`, `find_pet_scan`, `list_available_dates`,
`convert_date_format`, and `find_scan_by_type` are importable, each taking an optional `base_path`
that defaults to `DEFAULT_ADRC_ROOT` (from `$ADRC_ROOT`).

Encodes the layout contract:

```
<root>/<pid>/<YYYYMMDD>/anat/<pid>-<YYYYMMDD>_T1w.nii
<root>/<pid>/<YYYYMMDD>/pet/<pid>-<YYYYMMDD>_PET.nii
```

Scans with reconstruction suffixes (`_PET_128`, `_CorMPRAGE`) will not match — locate those with
`find` directly.

## find_t1w.py / find_pet.py

```bash
python3 find_t1w.py --folder "$ADRC_ROOT" --patient 110001 --date 01/15/2020 [-v]
python3 find_pet.py --folder "$ADRC_ROOT" --patient 110002 --date 03/10/2020 [-v]
```

Standalone single-purpose versions. All three flags required.

## interactive_scan_finder.py

```bash
python3 interactive_scan_finder.py
```

Menu loop for ad-hoc lookups. Uses `$ADRC_ROOT` if set, otherwise asks for the root once at startup.

## batch_copy_scans.py

```bash
python3 batch_copy_scans.py \
    -i ../../examples/scan_list.csv \
    -s "$ADRC_ROOT" -d /tmp/pull -t t1w \
    --preserve-structure -r report.csv -v
```

| Flag | Meaning |
|---|---|
| `-i, --input` | CSV; column 1 = subject ID, column 2 = `MM/DD/YYYY` |
| `-s, --source` | Dataset root |
| `-d, --destination` | Output directory |
| `-t, --type` | `t1w` or `pet` |
| `--preserve-structure` | Rebuild `<pid>/<YYYYMMDD>/<type>/` at the destination |
| `-r, --report` | Write a per-row status CSV |
| `-v, --verbose` | Verbose |

Requires `pandas`. See [`examples/scan_list.csv`](../../examples/scan_list.csv) for the input format.

**Always read the report.** Rows are marked `copied`, `not_found`, `copy_failed`, or `error` — a
missing scan is recorded, not raised, so a run can "succeed" while copying nothing.
