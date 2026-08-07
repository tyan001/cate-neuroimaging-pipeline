#!/bin/bash
#
# Merge a PET-only processed batch into the organized dataset tree.
#
# Usage:  ./pet_sync_batch.sh <batch_number> [source_dir]
# Example: ./pet_sync_batch.sh 12
#
# Environment:
#   PROCESSING_ROOT  where batches land after processing   (default: Processing)
#   ADRC_ROOT        the organized dataset root            (default: NWSI/ADRC)
#
# See sync_batch.sh for notes on the append-only merge semantics.
#
# Note: the log path here is ${ADRC_ROOT}/logs/pet_rsync_log/. The original
# version of this script wrote to NWSI/pet_rsync_log/, which did not match where
# the MRI scripts logged or where the logs actually accumulated on disk.

set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <batch_number> [source_dir]" >&2
  exit 1
fi

BATCH_NUMBER=$1
PROCESSING_ROOT="${PROCESSING_ROOT:-Processing}"
ADRC_ROOT="${ADRC_ROOT:-NWSI/ADRC}"

SOURCE_DIR="${2:-${PROCESSING_ROOT}/PET/batch${BATCH_NUMBER}/ADRC/}"
DEST_DIR="${ADRC_ROOT}/"
LOG_FILE="${ADRC_ROOT}/logs/pet_rsync_log/batch${BATCH_NUMBER}.log"

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
