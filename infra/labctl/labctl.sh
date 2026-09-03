#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR=/workspace
LAB_FILE="$ROOT_DIR/stand/import/Networks-Labs.unl"
LAB_ARCHIVE="$ROOT_DIR/stand/import/_Exports_pnetlab_10-2023.zip"
VESR_ROOT="$ROOT_DIR/stand/vesr"

info() { printf '==> %s\n' "$*"; }
ok() { printf ' OK  %s\n' "$*"; }
warn() { printf 'WARN %s\n' "$*" >&2; }
fail() { printf 'FAIL %s\n' "$*" >&2; return 1; }

ssh_base() {
  SSH=(ssh -p "${PNETLAB_SSH_PORT:-22}" -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)
  SCP=(scp -P "${PNETLAB_SSH_PORT:-22}" -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)

  if [[ -n "${PNETLAB_SSH_KEY:-}" ]]; then
    SSH+=(-i "$PNETLAB_SSH_KEY")
    SCP+=(-i "$PNETLAB_SSH_KEY")
  fi

  if [[ -n "${PNETLAB_SSH_PASSWORD:-}" ]]; then
    SSH=(sshpass -e "${SSH[@]}")
    SCP=(sshpass -e "${SCP[@]}")
    export SSHPASS="$PNETLAB_SSH_PASSWORD"
  fi
}

require_host() {
  if [[ -z "${PNETLAB_HOST:-}" ]]; then
    fail "PNETLAB_HOST не задан в data.env"
    return 1
  fi
  ssh_base
}

remote() {
  "${SSH[@]}" "${PNETLAB_SSH_USER:-root}@${PNETLAB_HOST}" "$@"
}

check_local_assets() {
  local rc=0
  info "Локальные материалы"

  [[ -s "$LAB_ARCHIVE" ]] && ok "архив PNETLab найден" || { fail "нет $LAB_ARCHIVE"; rc=1; }
  [[ -s "$LAB_FILE" ]] && ok "Networks-Labs.unl извлечён" || { fail "нет $LAB_FILE"; rc=1; }

  if [[ -s "$LAB_FILE" ]]; then
    xmllint --noout "$LAB_FILE" && ok "XML топологии корректен" || rc=1
    local nodes
    nodes="$(xmllint --xpath 'count(//node)' "$LAB_FILE")"
    [[ "$nodes" == "103" ]] && ok "в топологии 103 узла" || warn "ожидалось 103 узла, найдено: $nodes"
  fi

  [[ -f "$VESR_ROOT/templates/amd/vesr.yml" ]] && ok "шаблон vESR найден" || { fail "нет шаблона vESR"; rc=1; }

  if [[ -z "${VESR_IMAGE:-}" ]]; then
    warn "VESR_IMAGE не задан: шаблон установится, но Eltex-нода не запустится без hda.qcow2"
  elif [[ ! -s "$VESR_IMAGE" ]]; then
    fail "образ VESR_IMAGE не найден: $VESR_IMAGE"
    rc=1
  else
    ok "образ vESR найден"
  fi

  return "$rc"
}

check_remote() {
  require_host || return 1
  local rc=0 arch kvm_flags
  info "Удалённый PNETLab: ${PNETLAB_SSH_USER:-root}@${PNETLAB_HOST}"

  if ! remote true; then
    fail "SSH-подключение не установлено"
    return 1
  fi
  ok "SSH доступен"

  arch="$(remote 'uname -m')"
  if [[ "$arch" == "x86_64" || "$arch" == "amd64" ]]; then
    ok "архитектура x86_64"
  else
    fail "требуется x86_64, получено: $arch"
    rc=1
  fi

  kvm_flags="$(remote "grep -Ecm1 '(vmx|svm)' /proc/cpuinfo || true")"
  if [[ "$kvm_flags" -gt 0 ]] && remote 'test -c /dev/kvm'; then
    ok "nested virtualization и /dev/kvm доступны"
  else
    fail "нет VT-x/AMD-V или /dev/kvm; QEMU-ноды PNETLab не запустятся"
    rc=1
  fi

  remote 'test -d /opt/unetlab' && ok "/opt/unetlab найден" || { fail "PNETLab/EVE-NG не установлен"; rc=1; }

  if curl -kfsS --connect-timeout 5 "${PNETLAB_WEB_SCHEME:-http}://${PNETLAB_HOST}" >/dev/null; then
    ok "web-интерфейс отвечает"
  else
    fail "web-интерфейс не отвечает"
    rc=1
  fi

  return "$rc"
}

doctor() {
  local rc=0
  info "Управляющий контейнер"
  ok "контейнер запущен: $(uname -m)"
  check_local_assets || rc=1

  if [[ -n "${PNETLAB_HOST:-}" ]]; then
    check_remote || rc=1
  else
    warn "удалённый x86/KVM-хост пока не настроен; задайте PNETLAB_HOST в data.env"
    rc=1
  fi

  return "$rc"
}

render_vesr_config() {
  local source_file="$VESR_ROOT/scripts/config_vesr.py.in"
  local output_file="$1"
  VESR_USERNAME="${VESR_USERNAME:?VESR_USERNAME не задан}" \
  VESR_PASSWORD="${VESR_PASSWORD:?VESR_PASSWORD не задан}" \
    python3 - "$source_file" "$output_file" <<'PY'
import os
import pathlib
import sys

source = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
source = source.replace("__VESR_USERNAME__", repr(os.environ["VESR_USERNAME"]))
source = source.replace("__VESR_PASSWORD__", repr(os.environ["VESR_PASSWORD"]))
pathlib.Path(sys.argv[2]).write_text(source, encoding="utf-8")
PY
}

deploy() {
  require_host
  check_local_assets
  check_remote

  local stage
  stage="$(mktemp -d /tmp/labs-ib-deploy.XXXXXX)"
  trap 'rm -rf -- "$stage"' EXIT
  render_vesr_config "$stage/config_vesr.py"

  info "Загружаю файлы во временный каталог PNETLab"
  remote 'rm -rf /tmp/labs-ib-deploy && install -d -m 700 /tmp/labs-ib-deploy'
  "${SCP[@]}" \
    "$LAB_FILE" \
    "$stage/config_vesr.py" \
    "${PNETLAB_SSH_USER:-root}@${PNETLAB_HOST}:/tmp/labs-ib-deploy/"
  "${SCP[@]}" "$VESR_ROOT/templates/amd/vesr.yml" \
    "${PNETLAB_SSH_USER:-root}@${PNETLAB_HOST}:/tmp/labs-ib-deploy/vesr-amd.yml"
  "${SCP[@]}" "$VESR_ROOT/templates/intel/vesr.yml" \
    "${PNETLAB_SSH_USER:-root}@${PNETLAB_HOST}:/tmp/labs-ib-deploy/vesr-intel.yml"
  "${SCP[@]}" "$VESR_ROOT/templates_legacy/vesr.yml" \
    "${PNETLAB_SSH_USER:-root}@${PNETLAB_HOST}:/tmp/labs-ib-deploy/vesr-legacy.yml"

  if [[ -n "${VESR_IMAGE:-}" ]]; then
    "${SCP[@]}" "$VESR_IMAGE" "${PNETLAB_SSH_USER:-root}@${PNETLAB_HOST}:/tmp/labs-ib-deploy/hda.qcow2"
  fi

  info "Устанавливаю топологию и интеграцию vESR"
  remote "install -d /opt/unetlab/labs/Labs-IB \
    /opt/unetlab/html/templates/amd \
    /opt/unetlab/html/templates/intel \
    /opt/unetlab/html/templates_legacy \
    /opt/unetlab/scripts && \
    install -m 0644 /tmp/labs-ib-deploy/Networks-Labs.unl /opt/unetlab/labs/Labs-IB/Networks-Labs.unl && \
    install -m 0644 /tmp/labs-ib-deploy/vesr-amd.yml /opt/unetlab/html/templates/amd/vesr.yml && \
    install -m 0644 /tmp/labs-ib-deploy/vesr-intel.yml /opt/unetlab/html/templates/intel/vesr.yml && \
    install -m 0644 /tmp/labs-ib-deploy/vesr-legacy.yml /opt/unetlab/html/templates_legacy/vesr.yml && \
    install -m 0750 /tmp/labs-ib-deploy/config_vesr.py /opt/unetlab/scripts/config_vesr.py && \
    custom=/opt/unetlab/html/includes/custom_templates.yml && \
    if ! test -f \"\$custom\"; then printf 'custom_templates:\\n' > \"\$custom\"; fi && \
    if ! grep -Eq '^[[:space:]]*-[[:space:]]+name:[[:space:]]*vesr([[:space:]]|$)' \"\$custom\"; then \
      printf '  - name: vesr\\n    listname: Eltex vESR\\n' >> \"\$custom\"; \
    fi"

  if [[ -n "${VESR_IMAGE:-}" ]]; then
    remote "install -d /opt/unetlab/addons/qemu/vesr-1.18.2 && \
      install -m 0644 /tmp/labs-ib-deploy/hda.qcow2 /opt/unetlab/addons/qemu/vesr-1.18.2/hda.qcow2"
  fi

  remote '/opt/unetlab/wrappers/unl_wrapper -a fixpermissions'
  remote 'rm -rf /tmp/labs-ib-deploy'
  trap - EXIT
  rm -rf -- "$stage"
  ok "файлы развёрнуты"
  status
}

status() {
  require_host
  info "Состояние стенда"
  remote "set -e
    test -s /opt/unetlab/labs/Labs-IB/Networks-Labs.unl
    test -s /opt/unetlab/html/templates/amd/vesr.yml
    test -x /opt/unetlab/scripts/config_vesr.py
    printf 'lab=installed\\nvesr_template=installed\\n'
    if test -s /opt/unetlab/addons/qemu/vesr-1.18.2/hda.qcow2; then
      printf 'vesr_image=installed\\n'
    else
      printf 'vesr_image=missing\\n'
    fi
    printf 'kvm='; test -c /dev/kvm && printf 'available\\n' || printf 'missing\\n'"
}

case "${1:-doctor}" in
  doctor) doctor ;;
  deploy) deploy ;;
  status) status ;;
  shell) exec bash ;;
  *) fail "неизвестная команда: ${1:-}"; exit 2 ;;
esac
