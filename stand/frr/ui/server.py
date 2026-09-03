#!/usr/bin/env python3
import json
import mimetypes
import re
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import engine


STATIC_DIR = Path(__file__).parent / "static"


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, content, filename):
        body = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 524288:
            raise ValueError("некорректный размер запроса")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self.send_json({"status": "ok"})
            return
        if path == "/api/topology":
            self.send_json(engine.public_state())
            return
        if path == "/api/startup-configs":
            self.send_json({"ok": True, "result": engine.startup_configs()})
            return
        match = re.fullmatch(r"/api/nodes/([a-z0-9]+)/config", path)
        if match:
            try:
                node, content = engine.download_config(match.group(1))
                filename = re.sub(r"[^A-Za-z0-9_.-]+", "-", node["name"]) + ".cfg"
                self.send_text(content, filename)
            except ValueError as error:
                self.send_json({"ok": False, "error": str(error)}, 404)
            return
        self.serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
            routes = {
                "/api/nodes": engine.create_nodes,
                "/api/links": engine.create_link,
                "/api/actions": engine.perform_action,
                "/api/console/session": engine.start_console_session,
                "/api/console": engine.run_console,
                "/api/capture": engine.capture_interface,
            }
            callback = routes.get(path)
            if not callback:
                self.send_json({"error": "not found"}, 404)
                return
            self.send_json({"ok": True, "result": callback(payload)})
        except (ValueError, RuntimeError, TypeError, json.JSONDecodeError) as error:
            self.send_json({"ok": False, "error": str(error)}, 400)

    def do_PATCH(self):
        path = urlparse(self.path).path
        try:
            node_match = re.fullmatch(r"/api/nodes/([a-z0-9]+)", path)
            config_match = re.fullmatch(r"/api/startup-configs/([a-z0-9]+)", path)
            if node_match:
                result = engine.update_node(node_match.group(1), self.read_json())
            elif config_match:
                result = engine.update_startup_config(config_match.group(1), self.read_json())
            else:
                self.send_json({"error": "not found"}, 404)
                return
            self.send_json({"ok": True, "result": result})
        except (ValueError, RuntimeError, TypeError, json.JSONDecodeError) as error:
            self.send_json({"ok": False, "error": str(error)}, 400)

    def do_DELETE(self):
        path = urlparse(self.path).path
        try:
            node_match = re.fullmatch(r"/api/nodes/([a-z0-9]+)", path)
            link_match = re.fullmatch(r"/api/links/([a-z0-9]+)", path)
            if node_match:
                engine.delete_node(node_match.group(1))
            elif link_match:
                engine.delete_link(link_match.group(1))
            else:
                self.send_json({"error": "not found"}, 404)
                return
            self.send_json({"ok": True})
        except (ValueError, RuntimeError) as error:
            self.send_json({"ok": False, "error": str(error)}, 400)

    def serve_static(self, request_path):
        relative = "index.html" if request_path in ("", "/") else unquote(request_path.lstrip("/"))
        target = (STATIC_DIR / relative).resolve()
        root = STATIC_DIR.resolve()
        if root not in target.parents and target != root:
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *args):
        return


def shutdown(_signum, _frame):
    engine.stop_for_compose_shutdown()
    raise SystemExit(0)


if __name__ == "__main__":
    engine.prepare()
    signal.signal(signal.SIGTERM, shutdown)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
