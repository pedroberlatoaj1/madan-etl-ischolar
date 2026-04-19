#!/usr/bin/env bash
set -Eeuo pipefail

umask 027

APP_DIR="${APP_DIR:-/opt/madan-etl/app}"
DATA_DIR="${DATA_DIR:-/opt/madan-etl/data}"
BACKUP_DIR="${BACKUP_DIR:-/opt/madan-etl/backups}"
LOG_FILE="${LOG_FILE:-/var/log/madan-backup.log}"
LOCK_FILE="${LOCK_FILE:-/var/lock/madan-backup.lock}"
RCLONE_REMOTE="${RCLONE_REMOTE:-gdrive:madan-etl-backups}"
KEEP_LOCAL_BACKUPS="${KEEP_LOCAL_BACKUPS:-14}"
KEEP_REMOTE_BACKUPS="${KEEP_REMOTE_BACKUPS:-14}"
ALERT_EMAIL="${ALERT_EMAIL:-pedroberlatoaj1@gmail.com}"
HOSTNAME_SHORT="$(hostname -s 2>/dev/null || hostname)"
TIMESTAMP="$(date '+%Y-%m-%d-%H%M%S')"
ARCHIVE_NAME="madan-backup-${TIMESTAMP}.tar.gz"
ARCHIVE_PATH="${BACKUP_DIR}/${ARCHIVE_NAME}"

START_EPOCH="$(date +%s)"
TMP_DIR=""

log() {
    local level="$1"
    local event="$2"
    shift 2

    printf '%s level=%s event=%s' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$level" "$event"
    while (($#)); do
        printf ' %s' "$1"
        shift
    done
    printf '\n'
}

require_command() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        log ERROR dependency_missing "command=${cmd}"
        exit 1
    fi
}

send_failure_notification() {
    local subject="$1"
    local body="$2"

    if [[ -z "${ALERT_EMAIL}" ]]; then
        log WARN notify_skipped reason=no_alert_email
        return 0
    fi

    if command -v mail >/dev/null 2>&1; then
        if printf '%s\n' "$body" | mail -s "$subject" "$ALERT_EMAIL"; then
            log INFO notify_sent channel=mail "alert_email=${ALERT_EMAIL}"
            return 0
        fi
        log WARN notify_failed channel=mail "alert_email=${ALERT_EMAIL}"
        return 0
    fi

    if command -v sendmail >/dev/null 2>&1; then
        if {
            printf 'To: %s\n' "$ALERT_EMAIL"
            printf 'Subject: %s\n' "$subject"
            printf '\n%s\n' "$body"
        } | sendmail -t; then
            log INFO notify_sent channel=sendmail "alert_email=${ALERT_EMAIL}"
            return 0
        fi
        log WARN notify_failed channel=sendmail "alert_email=${ALERT_EMAIL}"
        return 0
    fi

    log WARN notify_unavailable "alert_email=${ALERT_EMAIL}" reason=no_mail_command
}

cleanup() {
    if [[ -n "${TMP_DIR}" && -d "${TMP_DIR}" ]]; then
        rm -rf "${TMP_DIR}"
    fi
}

handle_error() {
    local exit_code="$?"
    local line_no="$1"
    local command_text="$2"
    local duration_seconds="$(( $(date +%s) - START_EPOCH ))"

    log ERROR backup_failed \
        "line=${line_no}" \
        "exit_code=${exit_code}" \
        "duration_seconds=${duration_seconds}" \
        "archive_name=${ARCHIVE_NAME}" \
        "failed_command=$(printf '%q' "${command_text}")"

    send_failure_notification \
        "[madan-etl] Backup failed on ${HOSTNAME_SHORT}" \
        "Host: ${HOSTNAME_SHORT}
Archive: ${ARCHIVE_NAME}
Exit code: ${exit_code}
Line: ${line_no}
Command: ${command_text}
Log file: ${LOG_FILE}"

    exit "${exit_code}"
}

trap cleanup EXIT
trap 'handle_error "${LINENO}" "${BASH_COMMAND}"' ERR

backup_sqlite_files() {
    local db_count=0
    local target_dir="$1"

    while IFS= read -r -d '' db_path; do
        local db_name
        db_name="$(basename "${db_path}")"

        log INFO sqlite_backup_start "db=${db_name}"
        sqlite3 "${db_path}" ".timeout 5000" ".backup '${target_dir}/${db_name}'"
        log INFO sqlite_backup_done "db=${db_name}"
        db_count=$((db_count + 1))
    done < <(find "${DATA_DIR}" -maxdepth 1 -type f \( -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \) -print0 | sort -z)

    if [[ "${db_count}" -eq 0 ]]; then
        log ERROR sqlite_backup_missing reason=no_sqlite_files_found "data_dir=${DATA_DIR}"
        exit 1
    fi

    log INFO sqlite_backup_summary "count=${db_count}"
}

copy_non_sqlite_data() {
    local target_dir="$1"
    local item_count=0

    while IFS= read -r -d '' path; do
        cp -a "${path}" "${target_dir}/"
        item_count=$((item_count + 1))
    done < <(
        find "${DATA_DIR}" -mindepth 1 -maxdepth 1 \
            ! -name '*.db' \
            ! -name '*.sqlite' \
            ! -name '*.sqlite3' \
            ! -name '*-wal' \
            ! -name '*-shm' \
            -print0 | sort -z
    )

    log INFO non_sqlite_copy_summary "count=${item_count}"
}

copy_map_files() {
    local target_dir="$1"
    local map_count=0

    while IFS= read -r -d '' map_path; do
        cp -a "${map_path}" "${target_dir}/"
        map_count=$((map_count + 1))
    done < <(find "${APP_DIR}" -maxdepth 1 -type f -name 'mapa*.json' -print0 | sort -z)

    if [[ "${map_count}" -eq 0 ]]; then
        log ERROR map_copy_missing reason=no_map_files_found "app_dir=${APP_DIR}"
        exit 1
    fi

    log INFO map_copy_summary "count=${map_count}"
}

write_manifest() {
    local manifest_path="$1"
    cat > "${manifest_path}" <<EOF
backup_name=${ARCHIVE_NAME}
created_at_utc=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
hostname=${HOSTNAME_SHORT}
app_dir=${APP_DIR}
data_dir=${DATA_DIR}
rclone_remote=${RCLONE_REMOTE}
EOF
}

rotate_local_backups() {
    mapfile -t backups < <(find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'madan-backup-*.tar.gz' -printf '%f\n' | sort)

    if ((${#backups[@]} <= KEEP_LOCAL_BACKUPS)); then
        log INFO local_rotation_skipped "count=${#backups[@]}" "keep=${KEEP_LOCAL_BACKUPS}"
        return 0
    fi

    local delete_count="$(( ${#backups[@]} - KEEP_LOCAL_BACKUPS ))"
    local idx

    for ((idx = 0; idx < delete_count; idx++)); do
        rm -f "${BACKUP_DIR}/${backups[idx]}"
        log INFO local_backup_deleted "backup=${backups[idx]}"
    done
}

rotate_remote_backups() {
    if [[ "${KEEP_REMOTE_BACKUPS}" -le 0 ]]; then
        log INFO remote_rotation_skipped reason=disabled
        return 0
    fi

    mapfile -t remote_backups < <(
        rclone lsf "${RCLONE_REMOTE}" --files-only \
            | grep '^madan-backup-.*\.tar\.gz$' \
            | sort || true
    )

    if ((${#remote_backups[@]} <= KEEP_REMOTE_BACKUPS)); then
        log INFO remote_rotation_skipped "count=${#remote_backups[@]}" "keep=${KEEP_REMOTE_BACKUPS}"
        return 0
    fi

    local delete_count="$(( ${#remote_backups[@]} - KEEP_REMOTE_BACKUPS ))"
    local idx

    for ((idx = 0; idx < delete_count; idx++)); do
        rclone deletefile "${RCLONE_REMOTE}/${remote_backups[idx]}"
        log INFO remote_backup_deleted "backup=${remote_backups[idx]}"
    done
}

main() {
    require_command bash
    require_command find
    require_command flock
    require_command sqlite3
    require_command tar
    require_command gzip
    require_command rclone

    mkdir -p "${BACKUP_DIR}" "$(dirname "${LOCK_FILE}")"

    exec 9>"${LOCK_FILE}"
    if ! flock -n 9; then
        log WARN backup_already_running "lock_file=${LOCK_FILE}"
        exit 1
    fi

    log INFO backup_started \
        "archive_name=${ARCHIVE_NAME}" \
        "app_dir=${APP_DIR}" \
        "data_dir=${DATA_DIR}" \
        "backup_dir=${BACKUP_DIR}" \
        "remote=${RCLONE_REMOTE}"

    TMP_DIR="$(mktemp -d /tmp/madan-backup.XXXXXX)"
    local stage_dir="${TMP_DIR}/stage"
    local stage_data_dir="${stage_dir}/data"
    local stage_maps_dir="${stage_dir}/app-maps"
    local manifest_path="${stage_dir}/backup_manifest.txt"

    mkdir -p "${stage_data_dir}" "${stage_maps_dir}"

    backup_sqlite_files "${stage_data_dir}"
    copy_non_sqlite_data "${stage_data_dir}"
    copy_map_files "${stage_maps_dir}"
    write_manifest "${manifest_path}"

    tar -C "${stage_dir}" -czf "${ARCHIVE_PATH}" data app-maps backup_manifest.txt
    log INFO archive_created \
        "archive_path=${ARCHIVE_PATH}" \
        "size_bytes=$(stat -c%s "${ARCHIVE_PATH}")"

    rotate_local_backups

    rclone copyto "${ARCHIVE_PATH}" "${RCLONE_REMOTE}/${ARCHIVE_NAME}"
    log INFO remote_upload_done \
        "archive_name=${ARCHIVE_NAME}" \
        "remote=${RCLONE_REMOTE}"

    rotate_remote_backups

    log INFO backup_completed \
        "archive_name=${ARCHIVE_NAME}" \
        "duration_seconds=$(( $(date +%s) - START_EPOCH ))"
}

main "$@"
