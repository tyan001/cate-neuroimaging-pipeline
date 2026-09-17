# Dataset assembly

Merges processed batches into the assembled dataset, and publishes it onward to a shared mount.

Every script uses:

```bash
rsync -av --copy-links --ignore-existing
```

- `--ignore-existing` makes the merge **append-only** — re-running a batch never overwrites anything
  already in the tree. This is the safety property the whole workflow leans on.
- `--copy-links` dereferences symlinks so the destination is self-contained.

All four run `rsync` under `nohup` in the background and print the PID and log path.

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
