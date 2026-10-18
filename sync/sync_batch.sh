#!/bin/bash
#
# Merge a processed batch (MRI + PET together) into the organized dataset tree.
#
# Usage:  ./sync_batch.sh <batch_number> [source_dir]
# Example: ./sync_batch.sh 12
#          ./sync_batch.sh 12 /data/Processing/Both/batch12/ADRC/
#
# Paths are taken from the environment so this works outside the original host:
#   PROCESSING_ROOT  where batches land after processing   (default: Processing)
#   ADRC_ROOT        the organized dataset root            (default: NWSI/ADRC)
#
# --ignore-existing makes the merge append-only: re-running a batch never
# overwrites data already in the tree. --copy-links dereferences symlinks so the
# destination is self-contained. See docs/04-data-organization.md.

set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <batch_number> [source_dir]" >&2
  exit 1
fi

BATCH_NUMBER=$1
PROCESSING_ROOT="${PROCESSING_ROOT:-Processing}"
ADRC_ROOT="${ADRC_ROOT:-NWSI/ADRC}"

SOURCE_DIR="${2:-${PROCESSING_ROOT}/Both/batch${BATCH_NUMBER}/ADRC/}"
DEST_DIR="${ADRC_ROOT}/"
LOG_FILE="${ADRC_ROOT}/logs/mri_rsync_log/batch${BATCH_NUMBER}.log"

if [ ! -d "$SOURCE_DIR" ]; then
  echo "Error: source directory '$SOURCE_DIR' does not exist" >&2
  exit 1
fi

mkdir -p "$(dirname "$LOG_FILE")"

echo "Source: $SOURCE_DIR"
echo "Dest:   $DEST_DIR"
echo "Log:    $LOG_FILE"

nohup rsync -av --copy-links --ignore-existing "$SOURCE_DIR" "$DEST_DIR" > "$LOG_FILE" 2>&1 &
echo "rsync started with PID $!  —  monitor with: tail -f $LOG_FILE"
