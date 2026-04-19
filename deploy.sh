#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

ASSUME_YES=false
DRY_RUN=false

if [[ -t 1 ]]; then
  RED=$'\033[0;31m'
  GREEN=$'\033[0;32m'
  YELLOW=$'\033[1;33m'
  BLUE=$'\033[0;34m'
  BOLD=$'\033[1m'
  RESET=$'\033[0m'
else
  RED=''
  GREEN=''
  YELLOW=''
  BLUE=''
  BOLD=''
  RESET=''
fi

timestamp() {
  date '+%Y-%m-%d %H:%M:%S %Z'
}

log_info() {
  printf '%b[%s] %s%b\n' "$BLUE" "$(timestamp)" "$*" "$RESET"
}

log_warn() {
  printf '%b[%s] %s%b\n' "$YELLOW" "$(timestamp)" "$*" "$RESET"
}

log_error() {
  printf '%b[%s] %s%b\n' "$RED" "$(timestamp)" "$*" "$RESET" >&2
}

log_success() {
  printf '%b[%s] %s%b\n' "$GREEN" "$(timestamp)" "$*" "$RESET"
}

on_error() {
  local exit_code=$?
  local line_no=$1
  log_error "Deploy falhou na linha ${line_no} (exit code ${exit_code})."
  exit "$exit_code"
}

trap 'on_error $LINENO' ERR

usage() {
  cat <<'EOF'
Uso: ./deploy.sh [--yes] [--dry-run]

Opcoes:
  --yes, -y   confirma o deploy sem prompt interativo
  --dry-run   mostra o que entraria no deploy, sem alterar codigo nem servicos
  --help, -h  exibe esta ajuda
EOF
}

select_python() {
  if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
    printf '%s\n' "$PROJECT_DIR/.venv/bin/python"
    return
  fi

  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi

  if command -v python >/dev/null 2>&1; then
    command -v python
    return
  fi

  log_error "Nenhum interpretador Python encontrado."
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y)
      ASSUME_YES=true
      ;;
    --dry-run)
      DRY_RUN=true
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      log_error "Opcao desconhecida: $1"
      usage
      exit 1
      ;;
  esac
  shift
done

log_info "Iniciando deploy em ${PROJECT_DIR}"

current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$current_branch" == "HEAD" ]]; then
  log_error "Repositorio em detached HEAD. Abortei para evitar pull ambiguo."
  exit 1
fi

log_info "Atualizando referencias remotas..."
git fetch --prune

upstream_ref="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
if [[ -z "$upstream_ref" ]]; then
  if git show-ref --verify --quiet "refs/remotes/origin/${current_branch}"; then
    upstream_ref="origin/${current_branch}"
    log_warn "Branch sem upstream configurado; usando ${upstream_ref}."
  else
    log_error "Nao foi possivel determinar a branch remota de ${current_branch}."
    exit 1
  fi
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  log_warn "Ha alteracoes locais nao commitadas; git pull pode falhar."
  git status --short
fi

incoming_count="$(git rev-list --count HEAD.."${upstream_ref}")"
if [[ "$incoming_count" -gt 0 ]]; then
  log_info "Commits que vao entrar (${current_branch} <- ${upstream_ref}):"
  git --no-pager log --oneline --decorate HEAD.."${upstream_ref}"
else
  log_warn "Nenhum commit novo encontrado em ${upstream_ref}."
fi

if [[ "$ASSUME_YES" == false ]]; then
  if [[ ! -t 0 ]]; then
    log_error "Sem terminal interativo para confirmar. Use --yes para seguir."
    exit 1
  fi

  printf '%bContinuar com o deploy? [y/N] %b' "$BOLD" "$RESET"
  read -r confirmation
  shopt -s nocasematch
  if [[ ! "$confirmation" =~ ^(y|yes|s|sim)$ ]]; then
    shopt -u nocasematch
    log_warn "Deploy cancelado pelo operador."
    exit 0
  fi
  shopt -u nocasematch
fi

if [[ "$DRY_RUN" == true ]]; then
  log_success "Dry-run concluido. Nenhuma alteracao foi aplicada."
  exit 0
fi

log_info "Executando git pull --ff-only..."
git pull --ff-only

log_info "Limpando caches Python (__pycache__ e .pyc)..."
find . -name __pycache__ -type d -exec rm -rf {} +
find . -name '*.pyc' -delete

log_info "Reiniciando servicos systemd..."
sudo systemctl restart madan-webhook madan-worker

log_info "Aguardando 2 segundos para os servicos estabilizarem..."
sleep 2

systemctl is-active --quiet madan-webhook
systemctl is-active --quiet madan-worker

log_info "Status resumido dos servicos:"
set +o pipefail
systemctl status madan-webhook madan-worker --no-pager | head -10
set -o pipefail

python_bin="$(select_python)"
log_info "Validando import de validacao_pre_envio com ${python_bin}..."
imported_file="$("$python_bin" -c 'import os; import validacao_pre_envio as module; print(os.path.realpath(module.__file__))')"
expected_file="${PROJECT_DIR}/validacao_pre_envio.py"

if [[ "$imported_file" != "$expected_file" ]]; then
  log_error "validacao_pre_envio carregado de caminho inesperado: ${imported_file}"
  log_error "Esperado: ${expected_file}"
  exit 1
fi

deployed_commit="$(git rev-parse --short HEAD)"
log_success "Deploy concluido com sucesso em $(timestamp) | commit ${deployed_commit} | modulo validado em ${imported_file}"
