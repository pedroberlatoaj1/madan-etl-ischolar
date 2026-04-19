#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/madan-etl/app}"
DATA_DIR="${DATA_DIR:-/opt/madan-etl/data}"
BACKUP_DIR="${BACKUP_DIR:-/opt/madan-etl/backups}"
APP_USER="${APP_USER:-madan}"
APP_GROUP="${APP_GROUP:-madan}"
SERVICES=(${SERVICES:-madan-webhook madan-worker})

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

cleanup() {
    if [[ -n "${TMP_DIR}" && -d "${TMP_DIR}" ]]; then
        rm -rf "${TMP_DIR}"
    fi
}

trap cleanup EXIT

stop_services() {
    local service
    for service in "${SERVICES[@]}"; do
        log INFO service_stop_start "service=${service}"
        systemctl stop "${service}"
        log INFO service_stop_done "service=${service}"
    done
}

start_services() {
    local service
    for service in "${SERVICES[@]}"; do
        log INFO service_start_start "service=${service}"
        systemctl start "${service}"
        log INFO service_start_done "service=${service}"
    done
}

ensure_safe_path() {
    local path="$1"
    case "${path}" in
        /opt/madan-etl/data|/opt/madan-etl/app)
            ;;
        *)
            log ERROR unsafe_path "path=${path}"
            exit 1
            ;;
    esac
}

clear_directory() {
    local target_dir="$1"
    ensure_safe_path "${target_dir}"

    mkdir -p "${target_dir}"
    find "${target_dir}" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
}

restore_data_dir() {
    local extracted_root="$1"

    clear_directory "${DATA_DIR}"
    cp -a "${extracted_root}/data/." "${DATA_DIR}/"
    chown -R "${APP_USER}:${APP_GROUP}" "${DATA_DIR}"
    log INFO data_restored "data_dir=${DATA_DIR}"
}

restore_map_files() {
    local extracted_root="$1"

    ensure_safe_path "${APP_DIR}"
    find "${APP_DIR}" -maxdepth 1 -type f -name 'mapa*.json' -delete
    cp -a "${extracted_root}/app-maps/." "${APP_DIR}/"
    find "${APP_DIR}" -maxdepth 1 -type f -name 'mapa*.json' -exec chown "${APP_USER}:${APP_GROUP}" {} +
    log INFO maps_restored "app_dir=${APP_DIR}"
}

main() {
    require_command find
    require_command tar
    require_command systemctl
    require_command chown

    if (($# != 1)); then
        printf 'Uso: %s /caminho/para/madan-backup-YYYY-MM-DD-HHMMSS.tar.gz\n' "$0" >&2
        exit 1
    fi

    local archive_path="$1"

    if [[ ! -f "${archive_path}" ]]; then
        log ERROR backup_not_found "archive_path=${archive_path}"
        exit 1
    fi

    printf 'ATENCAO: isso vai parar %s e substituir %s e os mapas JSON de %s.\n' "${SERVICES[*]}" "${DATA_DIR}" "${APP_DIR}"
    printf "Digite 'yes' para continuar: "

    local confirmation
    read -r confirmation
    if [[ "${confirmation}" != "yes" ]]; then
        log WARN restore_aborted reason=confirmation_denied
        exit 1
    fi

    TMP_DIR="$(mktemp -d /tmp/madan-restore.XXXXXX)"
    tar -xzf "${archive_path}" -C "${TMP_DIR}"

    if [[ ! -d "${TMP_DIR}/data" ]]; then
        log ERROR invalid_backup_archive reason=data_dir_missing "archive_path=${archive_path}"
        exit 1
    fi

    if [[ ! -d "${TMP_DIR}/app-maps" ]]; then
        log ERROR invalid_backup_archive reason=app_maps_dir_missing "archive_path=${archive_path}"
        exit 1
    fi

    stop_services
    restore_data_dir "${TMP_DIR}"
    restore_map_files "${TMP_DIR}"
    start_services

    log INFO restore_completed "archive_path=${archive_path}"
}

main "$@"
