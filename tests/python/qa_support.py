"""Shared helpers for the Python script tests: module loading, subprocess runner, local fixture server.

Nothing here talks to anything but 127.0.0.1. Run the suite from the repository root:
    .venv/bin/python -m unittest discover -s tests/python -v
"""
import sys

sys.dont_write_bytecode = True   # keep __pycache__ out of the skill folders

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SITE_SCRIPTS = ROOT / "skills" / "qa-site-audit" / "scripts"
RELEASE_SCRIPT = ROOT / "skills" / "qa-release" / "scripts" / "release_qa_run.py"
QA_SEND = ROOT / "editions" / "hosted-bot" / "extras" / "qa-send"


def load_module(name, path):
    """Import a script by path (works for extensionless files such as qa-send)."""
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def run_script(path, *args, cwd=None, env=None, stdin=None):
    """Run a script with the current interpreter; returns CompletedProcess (text mode)."""
    full_env = {k: v for k, v in os.environ.items()
                if k.lower() not in ("http_proxy", "https_proxy", "all_proxy", "no_proxy")}
    full_env["PYTHONDONTWRITEBYTECODE"] = "1"
    full_env.update(env or {})
    return subprocess.run([sys.executable, str(path), *map(str, args)], cwd=cwd, env=full_env, input=stdin,
                          capture_output=True, text=True, timeout=120)


def fixture_bytes(name):
    return (FIXTURES / name).read_bytes()


def html(body, title="Test page", head=""):
    return (f"<!doctype html><html><head><meta charset=\"utf-8\"><title>{title}</title>{head}</head>"
            f"<body><main>{body}</main></body></html>").encode()


class FixtureServer:
    """HTTP server on 127.0.0.1 and a random free port.

    routes: path -> bytes | (status, headers_dict, body_bytes) | callable(handler) -> that tuple.
    Paths without a route are served from tests/python/fixtures/ when a file of that name exists, else 404.
    Every request is recorded in .requests as (method, path_with_query, headers_dict).
    """

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def _serve(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                outer.requests.append((self.command, self.path, dict(self.headers.items()), body))
                path = urlsplit(self.path).path
                route = outer.routes.get(path)
                if route is None:
                    f = FIXTURES / path.lstrip("/")
                    if path != "/" and f.is_file():
                        route = (200, {"Content-Type": "text/html; charset=utf-8"}, f.read_bytes())
                    else:
                        route = (404, {"Content-Type": "text/plain"}, b"not found")
                if callable(route):
                    route = route(self)
                if isinstance(route, bytes):
                    route = (200, {"Content-Type": "text/html; charset=utf-8"}, route)
                status, headers, payload = route
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(payload)

            do_GET = do_POST = do_HEAD = _serve

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, path="/"):
        return self.base + path

    def hits(self, path=None):
        return [r for r in self.requests if path is None or urlsplit(r[1]).path == path]


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
