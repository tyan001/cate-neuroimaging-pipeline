#!/bin/bash
#
# Publish the organized dataset to a shared network mount.
#
# Usage:  ./rsync_adrc_sync.sh [source_dir] [target_dir]
#
# Environment (used when the arguments are omitted):
#   ADRC_ROOT    the organized dataset root   (default: NWSI/ADRC)
#   SHARE_ROOT   the destination share        (no default — must be set or passed)
#
# Example:
#   SHARE_ROOT=/mnt/share/SiteData/ADRC ./rsync_adrc_sync.sh
#   ./rsync_adrc_sync.sh NWSI/ADRC/ /mnt/share/SiteData/ADRC/
#
# Uses --ignore-existing, so the share is append-only: files already published
# are never re-sent or overwritten.

set -euo pipefail

ADRC_ROOT="${ADRC_ROOT:-NWSI/ADRC}"
SOURCE_DIR="${1:-${ADRC_ROOT}/}"
TARGET_DIR="${2:-${SHARE_ROOT:-}}"

if [ -z "$TARGET_DIR" ]; then
    echo "Error: no target directory. Pass it as the second argument or set SHARE_ROOT." >&2
    echo "Usage: $0 [source_dir] [target_dir]" >&2
    exit 1
fi

TARGET_DIR="${TARGET_DIR%/}/"
LOG_FILE="${TARGET_DIR}ADRC_$(date +%Y%m%d).log"

if [ ! -d "$SOURCE_DIR" ]; then
    echo "Error: source directory '$SOURCE_DIR' does not exist" >&2
    exit 1
fi

if [ ! -d "$TARGET_DIR" ]; then
    echo "Creating target directory: $TARGET_DIR"
    mkdir -p "$TARGET_DIR"
fi

mkdir -p "$(dirname "$LOG_FILE")"

echo "Starting ADRC data sync at $(date)"
echo "Source: $SOURCE_DIR"
echo "Target: $TARGET_DIR"
echo "Log file: $LOG_FILE"

nohup rsync -av --copy-links --ignore-existing "$SOURCE_DIR" "$TARGET_DIR" > "$LOG_FILE" 2>&1 &

RSYNC_PID=$!
echo "Rsync started with PID: $RSYNC_PID"
echo "Monitor progress with: tail -f $LOG_FILE"
echo "Check if still running with: ps -p $RSYNC_PID"

echo $RSYNC_PID > /tmp/adrc_sync.pid
echo "PID saved to /tmp/adrc_sync.pid"
