import json
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path


STATE_FILE = Path(os.environ.get("TOPOLOGY_FILE", "/data/topology.json"))
ROUTER_IMAGE = os.environ.get("ROUTER_IMAGE", "labsib-frr-node:latest")
PC_IMAGE = os.environ.get("PC_IMAGE", "labsib-pc-node:latest")
NODE_IMAGE_ROOT = Path(os.environ.get("NODE_IMAGE_ROOT", "/app/node-images"))
MANAGEMENT_NETWORK = "labsib-management"
STATE_LOCK = threading.RLock()
SESSION_LOCK = threading.Lock()
SESSIONS = {}


def empty_state():
    return {
        "version": 2,
        "title": "Новая лабораторная",
        "nodes": {},
        "links": {},
        "startup_configs": {},
        "next_network": 1,
    }


def normalize_state(data):
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), dict) or not isinstance(data.get("links"), dict):
        return empty_state()
    data.setdefault("version", 2)
    data.setdefault("title", "Новая лабораторная")
    data.setdefault("startup_configs", {})
    data.setdefault("next_network", 1)
    for node in data["nodes"].values():
        router = node.get("type") == "router"
        node.setdefault("description", "")
        node.setdefault("ethernet", 4 if router else 1)
        node.setdefault("cpu", 1)
        node.setdefault("ram", 512 if router else 128)
        node.setdefault("console", "html5")
        node.setdefault("image", "FRRouting 10.7.1" if router else "Alpine Linux 3.22")
        node.setdefault("desired_running", False)
        node.setdefault("restore_on_start", False)
        node.setdefault("vpc_commands", [])
    for link in data["links"].values():
        link.setdefault("a_actual", "")
        link.setdefault("b_actual", "")
    return data


def load_state():
    if not STATE_FILE.exists():
        return empty_state()
    try:
        return normalize_state(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return empty_state()


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["version"] = 2
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_FILE)


def run(command, timeout=15, input_text=None):
    try:
        result = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode == 0, (result.stdout or result.stderr).strip()
    except (subprocess.TimeoutExpired, OSError) as error:
        return False, str(error)


def bounded_int(value, minimum, maximum, label):
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"поле {label} должно быть числом") from error
    if not minimum <= number <= maximum:
        raise ValueError(f"поле {label}: допустимо от {minimum} до {maximum}")
    return number


def safe_hostname(name):
    value = re.sub(r"[^a-zA-Z0-9-]+", "-", name).strip("-").lower()
    return (value or "node")[:48]


def container_exists(name):
    return run(["docker", "inspect", name])[0]


def container_running(name):
    ok, output = run(["docker", "inspect", "--format", "{{.State.Running}}", name])
    return ok and output == "true"


def ensure_management_network():
    if run(["docker", "network", "inspect", MANAGEMENT_NETWORK])[0]:
        return
    ok, output = run([
        "docker", "network", "create", "--driver", "bridge", "--internal",
        "--subnet", "172.31.255.0/24", "--label", "labsib.infrastructure=true",
        MANAGEMENT_NETWORK,
    ])
    if not ok and "already exists" not in output:
        raise RuntimeError(output)


def ensure_images():
    for image, directory in ((ROUTER_IMAGE, NODE_IMAGE_ROOT / "router"), (PC_IMAGE, NODE_IMAGE_ROOT / "pc")):
        if not directory.is_dir():
            raise RuntimeError(f"не найден контекст сборки {directory}")
        ok, output = run(["docker", "build", "-t", image, str(directory)], timeout=300)
        if not ok:
            raise RuntimeError(output)


def wait_router(name):
    required = {"zebra", "ripd", "ospfd", "bgpd", "staticd"}
    for _ in range(60):
        ok, output = run(["docker", "exec", name, "vtysh", "-c", "show daemons"])
        if ok and required.issubset(set(output.split())):
            return True
        time.sleep(0.25)
    return False


def port_names(node):
    if node["type"] == "router":
        return [f"gi1/0/{number}" for number in range(1, int(node["ethernet"]) + 1)]
    return [f"eth{number}" for number in range(int(node["ethernet"]))]


def used_ports(node_id, state):
    ports = set()
    for link in state["links"].values():
        if link["a"] == node_id:
            ports.add(link["a_if"])
        if link["b"] == node_id:
            ports.add(link["b_if"])
    return ports


def interfaces_for(node, state):
    assigned = {}
    for link in state["links"].values():
        if link["a"] == node["id"]:
            assigned[link["a_if"]] = {
                "link": link["id"], "peer": link["b"],
                "actual": link.get("a_actual", ""), "transport_ip": link["a_ip"],
            }
        elif link["b"] == node["id"]:
            assigned[link["b_if"]] = {
                "link": link["id"], "peer": link["a"],
                "actual": link.get("b_actual", ""), "transport_ip": link["b_ip"],
            }
    return [
        {"name": name, "used": name in assigned, **assigned.get(name, {"link": "", "peer": "", "actual": "", "transport_ip": ""})}
        for name in port_names(node)
    ]


def public_state():
    with STATE_LOCK:
        state = load_state()
    nodes = []
    for node in state["nodes"].values():
        item = dict(node)
        item.pop("vpc_commands", None)
        item["running"] = container_running(node["container"])
        item["interfaces"] = interfaces_for(node, state)
        startup = state["startup_configs"].get(node["id"], {})
        item["startup_saved"] = bool(startup.get("content"))
        item["startup_enabled"] = bool(startup.get("enabled"))
        nodes.append(item)
    return {"title": state["title"], "nodes": nodes, "links": list(state["links"].values())}


def create_container(node):
    image = ROUTER_IMAGE if node["type"] == "router" else PC_IMAGE
    command = [
        "docker", "create", "--name", node["container"], "--hostname", safe_hostname(node["name"]),
        "--label", "labsib.managed=true", "--label", f"labsib.node_id={node['id']}",
        "--label", f"labsib.node_type={node['type']}", "--label", f"labsib.display_name={node['name']}",
        "--restart", "no", "--network", MANAGEMENT_NETWORK, "--cpus", str(node["cpu"]),
        "--memory", f"{node['ram']}m", "--cap-add", "NET_ADMIN", "--cap-add", "NET_RAW",
    ]
    if node["type"] == "router":
        command.extend(["--cap-add", "SYS_ADMIN", "--sysctl", "net.ipv4.ip_forward=1", "--sysctl", "net.ipv4.conf.all.rp_filter=0"])
    command.append(image)
    ok, output = run(command)
    if not ok:
        raise RuntimeError(output)


def create_nodes(payload):
    node_type = str(payload.get("type", "")).lower()
    if node_type not in ("router", "pc"):
        raise ValueError("тип узла должен быть router или pc")
    base_name = str(payload.get("name", "")).strip()[:64]
    if not base_name:
        raise ValueError("задайте имя узла")
    count = bounded_int(payload.get("count", 1), 1, 10, "количество")
    ethernet = bounded_int(payload.get("ethernet", 4 if node_type == "router" else 1), 1, 16, "Ethernet")
    cpu = bounded_int(payload.get("cpu", 1), 1, 4, "CPU")
    ram = bounded_int(payload.get("ram", 512 if node_type == "router" else 128), 64, 4096, "RAM")
    x = max(80, min(1800, int(payload.get("x", 360))))
    y = max(80, min(1000, int(payload.get("y", 260))))
    description = str(payload.get("description", "")).strip()[:256]
    image = "FRRouting 10.7.1 (vESR equivalent)" if node_type == "router" else "Alpine Linux 3.22 (VPC)"
    created = []
    try:
        for index in range(count):
            node_id = uuid.uuid4().hex[:10]
            node = {
                "id": node_id, "name": base_name if count == 1 else f"{base_name}{index + 1}",
                "description": description, "type": node_type,
                "x": min(1800, x + index * 125), "y": min(1000, y + (index % 2) * 95),
                "container": f"labsib-node-{node_id}", "ethernet": ethernet, "cpu": cpu, "ram": ram,
                "console": "html5", "image": image, "desired_running": False,
                "restore_on_start": False, "vpc_commands": [],
            }
            create_container(node)
            created.append(node)
        with STATE_LOCK:
            state = load_state()
            for node in created:
                state["nodes"][node["id"]] = node
            save_state(state)
        return created
    except Exception:
        for node in created:
            run(["docker", "rm", "-f", node["container"]])
        raise


def interface_for(container, address):
    for _ in range(25):
        ok, output = run(["docker", "exec", container, "ip", "-o", "-4", "addr", "show"])
        if ok:
            for line in output.splitlines():
                if address in line:
                    return line.split()[1].split("@")[0].rstrip(":")
        time.sleep(0.15)
    return ""


def refresh_interfaces(node_id):
    with STATE_LOCK:
        state = load_state()
        node = state["nodes"].get(node_id)
        links = [dict(link) for link in state["links"].values() if node_id in (link["a"], link["b"])]
    if not node or not container_running(node["container"]):
        return
    resolved = {}
    for link in links:
        side = "a" if link["a"] == node_id else "b"
        resolved[link["id"]] = interface_for(node["container"], link[f"{side}_ip"])
    with STATE_LOCK:
        state = load_state()
        for link_id, actual in resolved.items():
            if link_id in state["links"]:
                side = "a" if state["links"][link_id]["a"] == node_id else "b"
                state["links"][link_id][f"{side}_actual"] = actual
        save_state(state)


def create_link(payload):
    a_id, b_id = str(payload.get("a", "")), str(payload.get("b", ""))
    a_if, b_if = str(payload.get("a_if", "")), str(payload.get("b_if", ""))
    if not a_id or not b_id or a_id == b_id:
        raise ValueError("выберите два разных узла")
    with STATE_LOCK:
        state = load_state()
        a_node, b_node = state["nodes"].get(a_id), state["nodes"].get(b_id)
        if not a_node or not b_node:
            raise ValueError("узел не найден")
        if a_if not in port_names(a_node) or b_if not in port_names(b_node):
            raise ValueError("выбран неизвестный интерфейс")
        if a_if in used_ports(a_id, state) or b_if in used_ports(b_id, state):
            raise ValueError("выбранный интерфейс уже занят")
        slot = int(state["next_network"])
        if slot > 250:
            raise ValueError("достигнут лимит соединений")
    link_id = uuid.uuid4().hex[:10]
    network = f"labsib-link-{link_id}"
    subnet, gateway = f"169.254.{slot}.0/29", f"169.254.{slot}.6"
    a_ip, b_ip = f"169.254.{slot}.1", f"169.254.{slot}.2"
    ok, output = run(["docker", "network", "create", "--driver", "bridge", "--internal", "--subnet", subnet, "--gateway", gateway,
                      "--label", "labsib.managed=true", "--label", f"labsib.link_id={link_id}", network])
    if not ok:
        raise RuntimeError(output)
    try:
        for address, node in ((a_ip, a_node), (b_ip, b_node)):
            ok, output = run(["docker", "network", "connect", "--ip", address, network, node["container"]])
            if not ok:
                raise RuntimeError(output)
    except RuntimeError:
        run(["docker", "network", "disconnect", "-f", network, a_node["container"]])
        run(["docker", "network", "disconnect", "-f", network, b_node["container"]])
        run(["docker", "network", "rm", network])
        raise
    link = {"id": link_id, "a": a_id, "b": b_id, "network": network, "subnet": subnet,
            "a_ip": a_ip, "b_ip": b_ip, "a_if": a_if, "b_if": b_if, "a_actual": "", "b_actual": ""}
    with STATE_LOCK:
        state = load_state()
        state["links"][link_id] = link
        state["next_network"] = slot + 1
        save_state(state)
    if container_running(a_node["container"]):
        refresh_interfaces(a_id)
    if container_running(b_node["container"]):
        refresh_interfaces(b_id)
    return link


def delete_link(link_id):
    with STATE_LOCK:
        state = load_state()
        link = state["links"].get(link_id)
        if not link:
            raise ValueError("соединение не найдено")
        a, b = state["nodes"].get(link["a"]), state["nodes"].get(link["b"])
    for node in (a, b):
        if node:
            run(["docker", "network", "disconnect", "-f", link["network"], node["container"]])
    run(["docker", "network", "rm", link["network"]])
    with STATE_LOCK:
        state = load_state()
        state["links"].pop(link_id, None)
        save_state(state)


def delete_node(node_id):
    with STATE_LOCK:
        state = load_state()
        node = state["nodes"].get(node_id)
        if not node:
            raise ValueError("узел не найден")
        link_ids = [key for key, link in state["links"].items() if node_id in (link["a"], link["b"])]
    for link_id in link_ids:
        delete_link(link_id)
    run(["docker", "rm", "-f", node["container"]])
    with STATE_LOCK:
        state = load_state()
        state["nodes"].pop(node_id, None)
        state["startup_configs"].pop(node_id, None)
        if not state["nodes"]:
            state["next_network"] = 1
        save_state(state)
    with SESSION_LOCK:
        for key in [key for key, value in SESSIONS.items() if value["node"] == node_id]:
            SESSIONS.pop(key, None)


def update_node(node_id, payload):
    with STATE_LOCK:
        state = load_state()
        node = state["nodes"].get(node_id)
        if not node:
            raise ValueError("узел не найден")
        if "x" in payload:
            node["x"] = max(50, min(1900, int(payload["x"])))
        if "y" in payload:
            node["y"] = max(50, min(1100, int(payload["y"])))
        if "name" in payload:
            name = str(payload["name"]).strip()[:64]
            if not name:
                raise ValueError("имя не может быть пустым")
            node["name"] = name
        if "description" in payload:
            node["description"] = str(payload["description"]).strip()[:256]
        if "ethernet" in payload:
            ethernet = bounded_int(payload["ethernet"], 1, 16, "Ethernet")
            available = set(port_names({**node, "ethernet": ethernet}))
            if not used_ports(node_id, state).issubset(available):
                raise ValueError("сначала удалите связи с портов, которые хотите убрать")
            node["ethernet"] = ethernet
        if "cpu" in payload:
            node["cpu"] = bounded_int(payload["cpu"], 1, 4, "CPU")
        if "ram" in payload:
            node["ram"] = bounded_int(payload["ram"], 64, 4096, "RAM")
        save_state(state)
        result = dict(node)
    run(["docker", "update", "--cpus", str(result["cpu"]), "--memory", f"{result['ram']}m", result["container"]])
    return result


def write_container_file(container, path, content):
    ok, output = run(["docker", "exec", "-i", container, "sh", "-c", f"cat > {path}"], input_text=content)
    if not ok:
        raise RuntimeError(output)


def apply_startup(node, startup):
    content = str(startup.get("content", ""))
    if not content:
        return
    if node["type"] == "router":
        write_container_file(node["container"], "/etc/frr/frr.conf", content.rstrip() + "\n")
        run(["docker", "exec", node["container"], "chown", "frr:frr", "/etc/frr/frr.conf"])
        run(["docker", "exec", node["container"], "chmod", "660", "/etc/frr/frr.conf"])
        ok, output = run(["docker", "restart", node["container"]], timeout=45)
        if not ok or not wait_router(node["container"]):
            raise RuntimeError(output or "не удалось применить startup-config")
    else:
        for command in startup.get("commands", []):
            run(["docker", "exec", node["container"], "sh", "-lc", command])


def reconnect_node(node, links):
    for link in links:
        side = "a" if link["a"] == node["id"] else "b"
        ok, output = run(["docker", "network", "connect", "--ip", link[f"{side}_ip"], link["network"], node["container"]])
        if not ok:
            raise RuntimeError(output)


def start_node(node_id, desired=True):
    with STATE_LOCK:
        state = load_state()
        node = dict(state["nodes"].get(node_id) or {})
        if not node:
            raise ValueError("узел не найден")
        links = [dict(link) for link in state["links"].values() if node_id in (link["a"], link["b"])]
        startup = dict(state["startup_configs"].get(node_id, {}))
        restore = bool(node.get("restore_on_start") and startup.get("enabled") and startup.get("content"))
    if not container_exists(node["container"]):
        create_container(node)
        reconnect_node(node, links)
    if not container_running(node["container"]):
        ok, output = run(["docker", "start", node["container"]], timeout=45)
        if not ok:
            raise RuntimeError(output)
    if node["type"] == "router" and not wait_router(node["container"]):
        raise RuntimeError("маршрутизатор не успел запустить FRR-daemons")
    refresh_interfaces(node_id)
    if node["type"] == "pc" and node.get("vpc_commands") and not restore:
        for command in node["vpc_commands"]:
            run(["docker", "exec", node["container"], "sh", "-lc", command])
    if restore:
        apply_startup(node, startup)
        refresh_interfaces(node_id)
    with STATE_LOCK:
        state = load_state()
        state["nodes"][node_id]["desired_running"] = desired
        state["nodes"][node_id]["restore_on_start"] = False
        save_state(state)


def stop_node(node_id, desired=False):
    with STATE_LOCK:
        state = load_state()
        node = state["nodes"].get(node_id)
        if not node:
            raise ValueError("узел не найден")
    if container_running(node["container"]):
        ok, output = run(["docker", "stop", "-t", "2", node["container"]], timeout=30)
        if not ok:
            raise RuntimeError(output)
    with STATE_LOCK:
        state = load_state()
        state["nodes"][node_id]["desired_running"] = desired
        save_state(state)


def restart_node(node_id):
    stop_node(node_id, desired=True)
    start_node(node_id, desired=True)


def wipe_node(node_id):
    with STATE_LOCK:
        state = load_state()
        node = dict(state["nodes"].get(node_id) or {})
        if not node:
            raise ValueError("узел не найден")
        links = [dict(link) for link in state["links"].values() if node_id in (link["a"], link["b"])]
        startup = state["startup_configs"].get(node_id, {})
    run(["docker", "rm", "-f", node["container"]], timeout=30)
    create_container(node)
    reconnect_node(node, links)
    with STATE_LOCK:
        state = load_state()
        current = state["nodes"][node_id]
        current["desired_running"] = False
        current["restore_on_start"] = bool(startup.get("enabled") and startup.get("content"))
        current["vpc_commands"] = []
        for link in state["links"].values():
            if link["a"] == node_id:
                link["a_actual"] = ""
            if link["b"] == node_id:
                link["b_actual"] = ""
        save_state(state)


def export_node_config(node_id):
    with STATE_LOCK:
        state = load_state()
        node = state["nodes"].get(node_id)
        if not node:
            raise ValueError("узел не найден")
    if not container_running(node["container"]):
        raise ValueError("для экспорта сначала запустите узел")
    if node["type"] == "router":
        ok, content = run(["docker", "exec", node["container"], "vtysh", "-c", "show running-config"], timeout=30)
        if not ok:
            raise RuntimeError(content)
        commands = []
    else:
        commands = list(node.get("vpc_commands", []))
        content = "\n".join(commands) + ("\n" if commands else "")
    with STATE_LOCK:
        state = load_state()
        state["startup_configs"][node_id] = {
            "content": content, "commands": commands, "enabled": True,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        save_state(state)
    return {"node": node_id, "bytes": len(content.encode("utf-8")), "enabled": True}


def startup_configs():
    with STATE_LOCK:
        state = load_state()
    return [
        {
            "node": node["id"], "name": node["name"], "type": node["type"],
            "content": state["startup_configs"].get(node["id"], {}).get("content", ""),
            "enabled": bool(state["startup_configs"].get(node["id"], {}).get("enabled")),
            "saved_at": state["startup_configs"].get(node["id"], {}).get("saved_at", ""),
        }
        for node in state["nodes"].values()
    ]


def update_startup_config(node_id, payload):
    with STATE_LOCK:
        state = load_state()
        node = state["nodes"].get(node_id)
        if not node:
            raise ValueError("узел не найден")
        config = state["startup_configs"].setdefault(node_id, {"content": "", "commands": []})
        if "content" in payload:
            content = str(payload["content"])
            if len(content.encode("utf-8")) > 262144:
                raise ValueError("startup-config слишком большой")
            config["content"] = content
            if node["type"] == "pc":
                config["commands"] = [line for line in content.splitlines() if line.strip()]
            config["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if "enabled" in payload:
            config["enabled"] = bool(payload["enabled"])
        save_state(state)
        return {"node": node_id, "enabled": bool(config.get("enabled")), "bytes": len(config.get("content", "").encode("utf-8"))}


def download_config(node_id):
    with STATE_LOCK:
        state = load_state()
        node = state["nodes"].get(node_id)
        config = state["startup_configs"].get(node_id, {})
    if not node or not config.get("content"):
        raise ValueError("сохранённая конфигурация не найдена")
    return node, config["content"]


def perform_action(payload):
    action = str(payload.get("action", ""))
    node_id = str(payload.get("node", ""))
    if action not in ("start", "stop", "restart", "wipe", "export"):
        raise ValueError("неизвестное действие")
    with STATE_LOCK:
        state = load_state()
        ids = [node_id] if node_id else list(state["nodes"])
        if node_id and node_id not in state["nodes"]:
            raise ValueError("узел не найден")
    results = []
    for current in ids:
        if action == "start":
            start_node(current)
        elif action == "stop":
            stop_node(current)
        elif action == "restart":
            restart_node(current)
        elif action == "wipe":
            wipe_node(current)
        else:
            results.append(export_node_config(current))
    return {"action": action, "count": len(ids), "results": results}


def logical_to_actual(node, logical):
    with STATE_LOCK:
        state = load_state()
        for interface in interfaces_for(node, state):
            if interface["name"] == logical:
                return interface.get("actual", "")
    return ""


def translate_aliases(node, command):
    def replace(match):
        logical = f"gi1/0/{match.group(1)}"
        actual = logical_to_actual(node, logical)
        if not actual:
            raise ValueError(f"интерфейс {logical} не соединён")
        return actual

    command = re.sub(r"(?i)gigabitethernet\s+1/0/(\d+)", replace, command)
    return re.sub(r"(?i)\bgi1/0/(\d+)\b", replace, command)


def prompt_for(node, session):
    name = safe_hostname(node["name"])
    if session["mode"] == "shell":
        return f"{name}$"
    if session["mode"] == "vpc":
        return f"{name}>"
    contexts = session["contexts"]
    if not contexts:
        return f"{name}#"
    raw = contexts[-1]["raw"].lower()
    if raw.startswith("interface"):
        return f"{name}(config-if)#"
    if raw.startswith("router ospf"):
        return f"{name}(config-ospf)#"
    if raw.startswith("router"):
        return f"{name}(config-router)#"
    if raw.startswith("address-family"):
        return f"{name}(config-router-af)#"
    return f"{name}(config)#"


def start_console_session(payload):
    node_id, mode = str(payload.get("node", "")), str(payload.get("mode", "frr"))
    with STATE_LOCK:
        node = load_state()["nodes"].get(node_id)
    if not node:
        raise ValueError("узел не найден")
    if not container_running(node["container"]):
        raise ValueError("сначала запустите узел")
    if mode == "frr" and node["type"] != "router":
        raise ValueError("FRR CLI доступна только на маршрутизаторе")
    if mode == "vpc" and node["type"] != "pc":
        raise ValueError("VPC CLI доступна только на виртуальном ПК")
    if mode not in ("frr", "shell", "vpc"):
        raise ValueError("неизвестный режим консоли")
    session_id = uuid.uuid4().hex
    session = {"node": node_id, "mode": mode, "contexts": []}
    with SESSION_LOCK:
        SESSIONS[session_id] = session
    if mode == "frr":
        banner = (
            "Labs-IB Router — FRRouting, ARM64\n"
            "Функциональный эквивалент vESR: IPv4/IPv6, static, RIP, OSPF, BGP.\n"
            "Порты на схеме gi1/0/N автоматически переводятся в Linux-интерфейсы. commit = сохранить."
        )
    elif mode == "vpc":
        banner = "Labs-IB Virtual PC\nКоманды: ip, show ip, ping, trace, arp, save, clear, help"
    else:
        banner = "Linux shell внутри узла. Для сохраняемой настройки ПК используй режим VPC CLI."
    return {"session": session_id, "prompt": prompt_for(node, session), "output": banner}


def show_interfaces(node):
    refresh_interfaces(node["id"])
    with STATE_LOCK:
        interfaces = interfaces_for(node, load_state())
    rows = ["Interface        Admin  Link  Linux", "---------------  -----  ----  --------"]
    for item in interfaces:
        link = "Up" if item["used"] and item.get("actual") else "Down"
        rows.append(f"{item['name']:<15}  Up     {link:<4}  {item.get('actual') or '-'}")
    return "\n".join(rows)


def frr_command(node, session, raw):
    command, lower = raw.strip(), raw.strip().lower()
    if lower in ("configure", "configure terminal", "conf t"):
        session["contexts"] = [{"raw": "configure", "command": "configure terminal"}]
        return ""
    if lower == "end":
        session["contexts"] = []
        return ""
    if lower == "exit":
        if session["contexts"]:
            session["contexts"].pop()
        return ""
    if lower in ("commit", "do commit", "write", "write memory"):
        ok, output = run(["docker", "exec", node["container"], "vtysh", "-c", "write memory"], timeout=30)
        if not ok:
            raise RuntimeError(output)
        return (output or "Configuration saved.") + "\nConfiguration committed and saved."
    if lower in ("confirm", "do confirm"):
        return "Configuration has been confirmed."
    if lower in ("reload", "reload system"):
        restart_node(node["id"])
        session["contexts"] = []
        return "System reloaded."
    if lower in ("show interfaces status", "show interface status"):
        return show_interfaces(node)
    if lower in ("ip firewall disable", "no ip firewall"):
        return "Compatibility command accepted; the lab router has no default filtering."
    if lower == "enable" and session["contexts"]:
        return "Compatibility command accepted."

    translated = translate_aliases(node, command)
    contexts = [item for item in session["contexts"] if item["command"]]
    parent = session["contexts"][-1]["raw"].lower() if session["contexts"] else ""
    if parent.startswith("router ospf") and lower.startswith("router-id "):
        translated = "ospf " + translated
    if lower.startswith("router ospf"):
        translated = "router ospf"

    command_line = ["docker", "exec", node["container"], "vtysh"]
    for context in contexts:
        command_line.extend(["-c", context["command"]])
    command_line.extend(["-c", translated])
    ok, output = run(command_line, timeout=30)
    if not ok:
        raise RuntimeError(output or "команда завершилась с ошибкой")
    if lower.startswith(("interface ", "router ospf", "router bgp", "address-family ")) or lower == "router rip":
        session["contexts"].append({"raw": command, "command": translated})
    return output or "OK"


def vpc_command(node, raw):
    text, lower = raw.strip(), raw.strip().lower()
    with STATE_LOCK:
        state = load_state()
        connected = [item for item in interfaces_for(node, state) if item["used"] and item.get("actual")]
    actual = connected[0]["actual"] if connected else ""
    if lower in ("help", "?"):
        return "ip ADDRESS/PREFIX [GATEWAY] | show ip | ping HOST | trace HOST | arp | save | clear"
    if lower in ("show", "show ip"):
        ok, output = run(["docker", "exec", node["container"], "sh", "-lc", "ip -br address; ip route"])
        if not ok:
            raise RuntimeError(output)
        return output
    if lower in ("arp", "show arp"):
        ok, output = run(["docker", "exec", node["container"], "ip", "neigh"])
        if not ok:
            raise RuntimeError(output)
        return output or "ARP table is empty"
    if lower.startswith(("ping ", "trace ", "traceroute ")):
        parts = text.split()
        if len(parts) != 2 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", parts[1]):
            raise ValueError("укажите один корректный адрес или hostname")
        tool = "traceroute" if lower.startswith(("trace ", "traceroute ")) else "ping"
        args = ["-m", "8", "-w", "2"] if tool == "traceroute" else ["-c", "4", "-W", "2"]
        _, output = run(["docker", "exec", node["container"], tool, *args, parts[1]], timeout=20)
        return output or "проверка связности завершилась без вывода"
    if lower.startswith("ip "):
        if not actual:
            raise ValueError("сначала соедините ПК с другим устройством")
        parts = text.split()
        if len(parts) not in (2, 3) or not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}", parts[1]):
            raise ValueError("формат: ip 192.0.2.2/24 [192.0.2.1]")
        commands = [f"ip addr replace {parts[1]} dev {actual}", f"ip link set {actual} up"]
        if len(parts) == 3:
            if not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", parts[2]):
                raise ValueError("некорректный gateway")
            commands.append(f"ip route replace default via {parts[2]} dev {actual}")
        ok, output = run(["docker", "exec", node["container"], "sh", "-lc", " && ".join(commands)])
        if not ok:
            raise RuntimeError(output)
        with STATE_LOCK:
            state = load_state()
            current = state["nodes"][node["id"]]
            current["vpc_commands"] = [item for item in current.get("vpc_commands", []) if not item.startswith(("ip addr replace ", "ip route replace default "))]
            current["vpc_commands"].extend(commands)
            save_state(state)
        return f"Address configured on {connected[0]['name']} ({actual})"
    if lower == "save":
        result = export_node_config(node["id"])
        return f"Startup configuration saved ({result['bytes']} bytes)."
    if lower == "clear":
        if actual:
            run(["docker", "exec", node["container"], "sh", "-lc", f"ip addr flush dev {actual} scope global; ip route del default 2>/dev/null || true"])
        with STATE_LOCK:
            state = load_state()
            state["nodes"][node["id"]]["vpc_commands"] = []
            save_state(state)
        return "VPC address configuration cleared"
    raise ValueError("неизвестная VPC-команда; введите help")


def run_console(payload):
    session_id, text = str(payload.get("session", "")), str(payload.get("command", "")).strip()
    if not text or len(text) > 8192:
        raise ValueError("пустая или слишком длинная команда")
    with SESSION_LOCK:
        session = SESSIONS.get(session_id)
    if not session:
        raise ValueError("сессия консоли завершена; откройте её заново")
    with STATE_LOCK:
        node = load_state()["nodes"].get(session["node"])
    if not node or not container_running(node["container"]):
        raise ValueError("узел остановлен")
    outputs = []
    for command in [line for line in text.splitlines() if line.strip()]:
        if session["mode"] == "frr":
            output = frr_command(node, session, command)
        elif session["mode"] == "vpc":
            output = vpc_command(node, command)
        else:
            ok, output = run(["docker", "exec", node["container"], "sh", "-lc", command], timeout=30)
            if not ok:
                raise RuntimeError(output or "команда завершилась с ошибкой")
        if output:
            outputs.append(output)
    with SESSION_LOCK:
        SESSIONS[session_id] = session
    return {"output": "\n".join(outputs), "prompt": prompt_for(node, session)}


def capture_interface(payload):
    node_id, logical = str(payload.get("node", "")), str(payload.get("interface", ""))
    with STATE_LOCK:
        node = load_state()["nodes"].get(node_id)
    if not node or not container_running(node["container"]):
        raise ValueError("сначала запустите узел")
    actual = logical_to_actual(node, logical)
    if not actual:
        raise ValueError("интерфейс не соединён или ещё не появился")
    ok, output = run(["docker", "exec", node["container"], "timeout", "8", "tcpdump", "-nn", "-l", "-i", actual, "-c", "20"], timeout=12)
    if not output:
        output = "За 8 секунд пакеты не обнаружены. Запустите ping и повторите захват."
    return {"interface": logical, "actual": actual, "output": output, "complete": ok}


def restore_desired_nodes():
    with STATE_LOCK:
        desired = [node["id"] for node in load_state()["nodes"].values() if node.get("desired_running")]
    for node_id in desired:
        try:
            start_node(node_id, desired=True)
        except (ValueError, RuntimeError):
            pass


def stop_for_compose_shutdown():
    with STATE_LOCK:
        containers = [node["container"] for node in load_state()["nodes"].values() if container_running(node["container"])]
    if containers:
        run(["docker", "stop", "-t", "2", *containers], timeout=120)


def prepare():
    ensure_images()
    ensure_management_network()
    restore_desired_nodes()
