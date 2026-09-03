#!/usr/bin/env bash
set -Eeuo pipefail

FRR_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$FRR_DIR/../.." && pwd)"
COMPOSE=(docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml")

printf 'Host: %s / %s\n' "$(uname -s)" "$(uname -m)"
printf 'Docker engine: %s\n' "$(docker info --format '{{.OSType}}/{{.Architecture}}')"

"${COMPOSE[@]}" config --quiet
echo 'OK: compose.yaml корректен'

for file in \
  "$FRR_DIR/nodes/router/daemons" \
  "$FRR_DIR/nodes/router/frr.conf" \
  "$FRR_DIR/nodes/pc/Dockerfile" \
  "$FRR_DIR/ui/server.py" \
  "$FRR_DIR/ui/engine.py" \
  "$FRR_DIR/ui/static/app.js"; do
  test -s "$file"
done
echo 'OK: шаблоны пустых узлов и web-конструктор найдены'

router_arch="$(docker image inspect labsib-frr-node:latest --format '{{.Architecture}}' 2>/dev/null || true)"
if [[ "$router_arch" != "arm64" ]]; then
  echo 'Ошибка: локальный ARM64-образ маршрутизатора ещё не собран. Выполните docker compose up -d --build.' >&2
  exit 1
fi
echo 'OK: локальный образ маршрутизатора собран для ARM64'

echo 'Стенд готов к сборке и запуску: ./lab up'
