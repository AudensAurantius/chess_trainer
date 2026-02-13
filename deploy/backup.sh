#!/usr/bin/env bash
# Backup the chess-data volume to a timestamped tar.gz archive.
# Usage: ./deploy/backup.sh
#
# Environment variables:
#   BACKUP_DIR     — where to store backups (default: ./backups)
#   CONTAINER_CMD  — podman or docker (auto-detected)
#   VOLUME_NAME    — volume to back up (default: chess_trainer_chess-data)
#   KEEP_DAYS      — delete backups older than N days (default: 14, 0=keep all)

set -euo pipefail

# Auto-detect container runtime
if [ -z "${CONTAINER_CMD:-}" ]; then
    if command -v podman &>/dev/null; then
        CONTAINER_CMD=podman
    elif command -v docker &>/dev/null; then
        CONTAINER_CMD=docker
    else
        echo "Error: neither podman nor docker found" >&2
        exit 1
    fi
fi

BACKUP_DIR="${BACKUP_DIR:-./backups}"
VOLUME_NAME="${VOLUME_NAME:-chess_trainer_chess-data}"
KEEP_DAYS="${KEEP_DAYS:-14}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/chess-trainer-${TIMESTAMP}.tar.gz"

mkdir -p "$BACKUP_DIR"

echo "Backing up volume '${VOLUME_NAME}' using ${CONTAINER_CMD}..."

$CONTAINER_CMD run --rm \
    -v "${VOLUME_NAME}:/source:ro" \
    -v "$(realpath "$BACKUP_DIR"):/backup" \
    alpine:3 \
    tar czf "/backup/chess-trainer-${TIMESTAMP}.tar.gz" -C /source .

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Backup complete: ${BACKUP_FILE} (${SIZE})"

# Prune old backups
if [ "$KEEP_DAYS" -gt 0 ]; then
    PRUNED=$(find "$BACKUP_DIR" -name "chess-trainer-*.tar.gz" -mtime +"$KEEP_DAYS" -print -delete | wc -l)
    if [ "$PRUNED" -gt 0 ]; then
        echo "Pruned ${PRUNED} backup(s) older than ${KEEP_DAYS} days"
    fi
fi
