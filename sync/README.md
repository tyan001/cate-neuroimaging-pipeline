# Dataset assembly

Merges processed batches into the assembled dataset, and publishes it onward to a shared mount.

Every script uses:

```bash
rsync -av --copy-links --ignore-existing
```

- `--ignore-existing` makes the merge **append-only** — re-running a batch never overwrites anything
  already in the tree. This is the safety property the whole workflow leans on.
- `--copy-links` dereferences symlinks so the destination is self-contained.

The four shell scripts run `rsync` under `nohup` in the background and print the PID and log path.

---

## Configuration

Paths come from the environment, with the argument taking precedence:

| Variable | Default | Meaning |
|---|---|---|
| `PROCESSING_ROOT` | `Processing` | Where batches land after processing |
| `ADRC_ROOT` | `NWSI/ADRC` | The assembled dataset |
| `SHARE_ROOT` | *(none)* | Destination share, for `rsync_adrc_sync.sh` |

```bash
export PROCESSING_ROOT=/data/Processing
export ADRC_ROOT=/data/NWSI/ADRC
```

> **Permissions.** These scripts do **not** call `sudo`. Run them under an account that can write to
> the destination, or prefix with `sudo` yourself. (The originals hardcoded `sudo`; that was removed
> so the scripts are safe to run anywhere.)

---

## Merging a batch

### merge_batch.py (checked merge, recommended)

```bash
python3 merge_batch.py /data/Processing/Both/batch87/ADRC --dest /data/NWSI/ADRC            # plan
python3 merge_batch.py /data/Processing/Both/batch87/ADRC --dest /data/NWSI/ADRC --execute  # copy

# or by batch number, with the same environment variables as the shell scripts
ADRC_ROOT=/data/NWSI/ADRC PROCESSING_ROOT=/data/Processing python3 merge_batch.py 87 --execute
```

Without `--execute` it only prints the plan. The copy is the same append-only
`rsync -a --copy-links --ignore-existing`, run in the foreground (wrap it in `nohup` for big
batches), but only for files that pass these checks:

| In the batch | What happens |
|---|---|
| New files | Copied |
| A file the main folder already has, same content | Left alone (a re-delivered file with a different modification time counts as the same) |
| A file the main folder already has, different content | Left alone, listed as a **conflict** |
| A `freesurfer741/<scan>/` or SUVR pair folder that the main folder already has | Skipped as a whole, so two runs never get mixed in one folder |
| A failed or unfinished recon-all (`recon-all.error`, missing outputs) | Skipped; the scan in `anat/` is still copied |
| An SUVR pair folder without `res/<pair>_suvr_combined_cerebellum.csv` | Skipped; the PET is still copied |
| A scan whose filename date is not its session folder | Skipped |
| `freesurfer741/fsaverage` | Skipped. recon-all links it to the FreeSurfer install, and following the link would copy a 480 MB template into every session (about a third of batch87). |
| `fs_logs/ADRC.log` | Copied to `logs/fs_logs/<batch>.log`. Other batch-level folders go under `logs/`. |

Skipped folders are the ones the next step reprocesses. After merging, run
`pipeline/7_DirectoryStats/find_missing.py` on the main folder.
`--include-incomplete` copies failed or unfinished folders anyway.

When it finishes, it checks that every copied file is in the main folder with the right size.
It exits nonzero if rsync or that check fails. The plan and the rsync output are logged to
`${ADRC_ROOT}/logs/merge_logs/<batch>_<timestamp>.log`.

### Shell scripts

These copy the whole batch as-is, in the background, without the checks above.

```bash
./sync_batch.sh 12          # combined MRI + PET batch
./mri_sync_batch.sh 12      # MRI-only batch
./pet_sync_batch.sh 12      # PET-only batch
```

Each takes a batch number and an optional explicit source directory:

```bash
./sync_batch.sh 12 /data/Processing/Both/batch12/ADRC/
```

Defaults resolve to `${PROCESSING_ROOT}/{Both,MRI,PET}/batch<N>/ADRC/` → `${ADRC_ROOT}/`.

Logs go to `${ADRC_ROOT}/logs/mri_rsync_log/batch<N>.log` (or `pet_rsync_log/` for PET):

```bash
tail -f /data/NWSI/ADRC/logs/mri_rsync_log/batch12.log
```

## Publishing to a share

```bash
SHARE_ROOT=/mnt/share/SiteData/ADRC ./rsync_adrc_sync.sh
# or explicitly
./rsync_adrc_sync.sh /data/NWSI/ADRC/ /mnt/share/SiteData/ADRC/
```

Creates the target and log directories if needed, writes a dated log
(`ADRC_YYYYMMDD.log`) at the destination, and saves the rsync PID to `/tmp/adrc_sync.pid`.

```bash
ps -p $(cat /tmp/adrc_sync.pid)          # still running?
```

---

## Migrating without derivatives

To copy source data only — e.g. re-processing under a newer FreeSurfer:

```bash
rsync -av --exclude='*/freesurfer741/' --exclude='*/suvr/' --exclude='*/sitedata_mri/' \
      /source/ADRC/ /destination/ADRC/
```

Keeps `anat/`, `pet/`, `ct/`, `modalities/`; drops everything reproducible.

See [docs/04-data-organization.md](../docs/04-data-organization.md) for the layout these scripts
build.
