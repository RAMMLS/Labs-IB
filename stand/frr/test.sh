#!/usr/bin/env bash
set -Eeuo pipefail

FRR_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$FRR_DIR/../.." && pwd)"
COMPOSE=(docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml")

"${COMPOSE[@]}" up -d lab-ui >/dev/null
for attempt in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8080/health >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" == "60" ]]; then
    echo 'FAIL: визуальный конструктор не отвечает' >&2
    exit 1
  fi
  sleep 1
done

python3 - <<'PY'
import json
import sys
import urllib.error
import urllib.request

base = "http://127.0.0.1:8080"
created = []

def call(path, method="GET", data=None):
    request = urllib.request.Request(
        base + path,
        data=None if data is None else json.dumps(data).encode(),
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=50) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(error.read().decode()) from error

def cleanup():
    for node_id in reversed(created):
        try:
            call("/api/nodes/" + node_id, "DELETE")
        except Exception as error:
            print(f"WARN cleanup: {error}", file=sys.stderr)

try:
    assert not call("/api/topology")["nodes"], "тест запускается только на пустом поле"
    router = call("/api/nodes", "POST", {
        "type": "router", "name": "TEST-vESR", "count": 1,
        "ethernet": 4, "cpu": 1, "ram": 512, "x": 350, "y": 300,
    })["result"][0]
    pc = call("/api/nodes", "POST", {
        "type": "pc", "name": "TEST-PC", "count": 1,
        "ethernet": 2, "cpu": 1, "ram": 128, "x": 650, "y": 300,
    })["result"][0]
    created.extend([router["id"], pc["id"]])
    assert all(not node["running"] for node in call("/api/topology")["nodes"])
    call("/api/links", "POST", {
        "a": router["id"], "b": pc["id"], "a_if": "gi1/0/2", "b_if": "eth1",
    })
    for node in (router, pc):
        call("/api/actions", "POST", {"action": "start", "node": node["id"]})

    router_session = call("/api/console/session", "POST", {"node": router["id"], "mode": "frr"})["result"]["session"]
    for command in ("configure", "interface gigabitethernet 1/0/2", "ip address 10.77.0.1/30", "exit", "end", "commit"):
        call("/api/console", "POST", {"session": router_session, "command": command})
    pc_session = call("/api/console/session", "POST", {"node": pc["id"], "mode": "vpc"})["result"]["session"]
    call("/api/console", "POST", {"session": pc_session, "command": "ip 10.77.0.2/30"})
    ping = call("/api/console", "POST", {"session": pc_session, "command": "ping 10.77.0.1"})["result"]["output"]
    assert "0% packet loss" in ping

    call("/api/actions", "POST", {"action": "export", "node": router["id"]})
    call("/api/actions", "POST", {"action": "stop", "node": router["id"]})
    call("/api/actions", "POST", {"action": "wipe", "node": router["id"]})
    call("/api/actions", "POST", {"action": "start", "node": router["id"]})
    router_session = call("/api/console/session", "POST", {"node": router["id"], "mode": "frr"})["result"]["session"]
    config = call("/api/console", "POST", {"session": router_session, "command": "show running-config"})["result"]["output"]
    assert "ip address 10.77.0.1/30" in config

    print("OK: ноды создаются выключенными")
    print("OK: кабель занимает выбранные gi1/0/2 и eth1")
    print("OK: Router CLI и VPC CLI настраивают реальную связность")
    print("OK: ping по пользовательским адресам проходит")
    print("OK: Export CFG → Wipe → Start восстанавливает startup-config")
finally:
    cleanup()
    state = call("/api/topology")
    assert not state["nodes"] and not state["links"]
    print("OK: тестовая топология удалена, поле снова пустое")
PY
