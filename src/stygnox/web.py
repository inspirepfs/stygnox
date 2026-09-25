"""Installed neutral Stygnox Web operator console."""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
import ipaddress
import json
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import adoption
from .operator import OperatorSurfaceError, dispatch_action, operator_snapshot
from .product import PRODUCT
from . import web_brand

MAX_BODY = 128 * 1024


class WebError(RuntimeError):
    pass


def _asset(name: str) -> bytes:
    allowed = {
        "design-tokens.css", "components.css", "operator.css", "operator.js",
        "stygnox-icon-128.png", "stygnox-logo-800x300.png",
    }
    if name not in allowed:
        raise WebError("unknown packaged Web asset")
    if name.endswith(".png"):
        try:
            return web_brand.asset_bytes(name)
        except KeyError as exc:
            raise WebError("unknown packaged Web asset") from exc
    return resources.files("stygnox.web_assets").joinpath(name).read_bytes()


def _index_html(csrf: str) -> bytes:
    page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="stygnox-csrf" content="{csrf}"><title>Stygnox Operator Console</title>
<link rel="icon" href="/assets/stygnox-icon-128.png"><link rel="stylesheet" href="/assets/design-tokens.css"><link rel="stylesheet" href="/assets/components.css"><link rel="stylesheet" href="/assets/operator.css"></head>
<body><header class="operator-header"><div class="operator-header__inner"><a class="operator-brand" href="/" aria-label="Stygnox operator console"><img src="/assets/stygnox-icon-128.png" alt=""><span>Styg<b>Nox</b></span></a><div class="operator-head-state" aria-label="Live operator state"><div class="head-stack"><small>Model</small><strong id="model">—</strong><small>Effort</small><strong id="effort">—</strong></div><div class="head-stack"><small>Live</small><strong id="live">—</strong><small>PID</small><strong id="pid">—</strong></div></div></div></header>
<main class="operator-shell operator-main"><section class="sn-panel sn-panel--glow hero-panel"><div class="hero-copy"><div class="section-kicker">Operator authority · evidence first</div><h1>Autonomy without surrendering authority.</h1><p>Installed Stygnox Web surface for admission, transaction, recovery and controller actions. Every mutation remains preview-bound and explicitly confirmed.</p></div><img class="hero-logo" src="/assets/stygnox-logo-800x300.png" alt="Stygnox"></section>
<section class="status-strip" aria-label="Current status"><div class="status-cell"><small>Adoption</small><span id="adoption-state" class="state-badge">—</span></div><div class="status-cell"><small>Transaction</small><span id="transaction-state" class="state-badge">—</span></div><div class="status-cell"><small>Controller</small><span id="controller-state" class="state-badge">—</span></div><div class="status-cell"><small>Journey</small><strong id="journey">—</strong></div></section>
<section class="operator-grid"><article class="panel span-5"><div class="panel-title"><h2>Project authority</h2><span class="meta" id="head">—</span></div><dl class="kv"><dt>Worktree</dt><dd id="project-path">—</dd><dt>Operator</dt><dd id="operator">—</dd><dt>Provider</dt><dd id="provider">—</dd><dt>Reserve</dt><dd id="reserve">—</dd><dt>Wait limits</dt><dd id="wait-limits">—</dd><dt>Runtime records</dt><dd id="runtime-count">0</dd></dl></article>
<article class="panel span-7"><div class="panel-title"><h2>Carry-forward / reconciliation attribution</h2><span class="meta">display-only classification</span></div><div id="attribution" class="attribution"></div><div class="attribution-note"><strong>No automatic adoption or reattribution.</strong> External and unresolved paths require an explicit human decision before any future carry-forward action.</div></article>
<article class="panel span-12"><div class="panel-title"><h2>Authority actions</h2><span class="meta">preview → exact confirmation</span></div><div class="action-grid"><div class="action-card"><h3>Operator / adoption</h3><div class="field"><label for="operator-input">Named operator</label><input id="operator-input" autocomplete="off" placeholder="Operator name"></div><div class="field"><label for="dirty-evidence">Dirty recovery attestation path (dirty journeys only)</label><input id="dirty-evidence" autocomplete="off" placeholder="/path/to/attestation.json"></div><div class="field"><label for="preview-input">Exact adoption preview SHA-256</label><input id="preview-input" autocomplete="off"></div><div class="button-row"><button class="sn-btn sn-btn--secondary" onclick="stygnoxAction('adopt.preview')">Preview adoption</button><button class="sn-btn sn-btn--primary" onclick="stygnoxAction('adopt.handoff')">Confirm handoff</button></div></div>
<div class="action-card"><h3>Transaction / recovery</h3><div class="field"><label for="stop-reason">Safe-stop reason</label><select id="stop-reason"><option>operator-abort</option><option>interrupted</option><option>authority-revoked</option><option>qualification</option></select></div><div class="field"><label for="recovery-preview-input">Exact recovery preview SHA-256</label><input id="recovery-preview-input" autocomplete="off"></div><div class="button-row"><button class="sn-btn sn-btn--primary" onclick="stygnoxAction('transaction.begin')">Begin transaction</button><button class="sn-btn warn" onclick="stygnoxAction('transaction.stop')">Safe stop</button><button class="sn-btn sn-btn--secondary" onclick="stygnoxAction('recovery.preview')">Preview recovery</button><button class="sn-btn danger" onclick="stygnoxAction('recovery.restore')">Restore baseline</button></div></div>
<div class="action-card"><h3>Controller authority</h3><div class="field"><label for="objective">One-turn objective</label><textarea id="objective" placeholder="Bounded implementation objective"></textarea></div><div class="field"><label for="repo-authority">Repository authority</label><select id="repo-authority"><option value="read-only">read-only</option><option value="write">write</option></select></div><div class="field"><label for="run-preview-input">Exact run preview SHA-256</label><input id="run-preview-input" autocomplete="off"></div><div class="button-row"><button class="sn-btn sn-btn--primary" onclick="stygnoxAction('controller.activate')">Activate</button><button class="sn-btn sn-btn--secondary" onclick="stygnoxAction('controller.run-preview')">Preview run</button><button class="sn-btn sn-btn--primary" onclick="stygnoxAction('controller.run')">Run confirmed turn</button><button class="sn-btn warn" onclick="stygnoxAction('controller.deactivate')">Deactivate</button></div></div>
<div class="action-card"><h3>Action evidence</h3><div id="notice" class="notice" role="status" aria-live="polite"></div><pre id="action-result" class="evidence" aria-label="Latest action result">No action yet.</pre></div></div></article>
<article class="panel span-12"><div class="panel-title"><h2>Runtime evidence summary</h2><span class="meta">controller-owned · ignored</span></div><pre id="evidence-json" class="evidence">{{}}</pre></article></section>
<footer class="footer"><span>Stygnox · Plan · Execute · Evidence · Evolve</span><span>Web surface is loopback-only</span></footer></main><script src="/assets/operator.js"></script></body></html>'''
    return page.encode("utf-8")


class OperatorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], project: Path):
        self.project = adoption.resolve_worktree(project)
        self.csrf = secrets.token_urlsafe(32)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server: OperatorServer

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet deterministic local console
        return

    def _json(self, status: int, value: Any) -> None:
        data = json.dumps(value, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _bytes(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/":
                self._bytes(HTTPStatus.OK, _index_html(self.server.csrf), "text/html; charset=utf-8")
                return
            if path == "/health":
                self._json(HTTPStatus.OK, {"ok": True, "product": PRODUCT.name, "version": PRODUCT.version})
                return
            if path == "/api/snapshot":
                self._json(HTTPStatus.OK, operator_snapshot(self.server.project, server_pid=self.server.server_address[1] and __import__('os').getpid()))
                return
            if path.startswith("/assets/"):
                name = path.removeprefix("/assets/")
                content_type = "text/css; charset=utf-8" if name.endswith(".css") else "application/javascript; charset=utf-8" if name.endswith(".js") else "image/png"
                self._bytes(HTTPStatus.OK, _asset(name), content_type)
                return
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "unsupported Web route"})
        except (WebError, OperatorSurfaceError, adoption.AdoptionError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/action":
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "unsupported Web mutation route"})
            return
        if self.headers.get("X-Stygnox-CSRF") != self.server.csrf:
            self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "CSRF validation failed"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if size < 1 or size > MAX_BODY:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid request body size"})
            return
        try:
            value = json.loads(self.rfile.read(size).decode("utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("payload", {}), dict):
                raise WebError("action request must be a JSON object")
            result = dispatch_action(self.server.project, str(value.get("action") or ""), value.get("payload") or {})
            self._json(HTTPStatus.OK, {"ok": True, **result})
        except (json.JSONDecodeError, UnicodeDecodeError, WebError, OperatorSurfaceError, adoption.AdoptionError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})


def _loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stygnox web", description="Installed neutral Stygnox Web operator console.")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Git worktree")
    parser.add_argument("--host", default="127.0.0.1", help="loopback host only; remote access requires an explicit security policy")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    import sys
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not _loopback(args.host):
        print("stygnox: web refused: Web is loopback-only; non-loopback binding requires an explicit remote-access security policy", file=sys.stderr)
        return 2
    try:
        server = OperatorServer((args.host, args.port), args.project)
    except (OSError, adoption.AdoptionError) as exc:
        print(f"stygnox: web refused: {exc}", file=sys.stderr)
        return 2
    host, port = server.server_address[:2]
    print(f"Stygnox Web {PRODUCT.version} · http://{host}:{port} · project={server.project}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
