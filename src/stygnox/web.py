"""Installed neutral Stygnox Web operator console."""
from __future__ import annotations

import argparse
import base64
import binascii
import getpass
import hashlib
import hmac
from collections.abc import Sequence
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
import ipaddress
import json
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import adoption
from .operator import OperatorSurfaceError, dispatch_action, operator_snapshot
from .product import PRODUCT
from . import web_brand

MAX_BODY = 128 * 1024
WEB_AUTH_RECORD = "web-auth.json"
WEB_AUTH_SCHEMA = "stygnox_web_auth_v1"
WEB_AUTH_ITERATIONS = 260_000


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
<main class="operator-shell operator-main"><section class="sn-panel sn-panel--glow hero-panel"><div class="hero-copy"><div class="section-kicker">Operator authority · evidence first</div><h1>Autonomy without surrendering authority.</h1><p>Installed Stygnox Web surface aligned to the shared TUI/operator model. State, policy, evidence and mutations use the same installed-product semantics.</p></div><img class="hero-logo" src="/assets/stygnox-logo-800x300.png" alt="Stygnox"></section>
<section class="status-strip" aria-label="Current status"><div class="status-cell"><small>Adoption</small><span id="adoption-state" class="state-badge">—</span></div><div class="status-cell"><small>Transaction</small><span id="transaction-state" class="state-badge">—</span></div><div class="status-cell"><small>Controller</small><span id="controller-state" class="state-badge">—</span></div><div class="status-cell"><small>Journey</small><strong id="journey">—</strong></div></section>
<section class="operator-grid">
<article class="panel span-6"><div class="panel-title"><h2>Operator state</h2><span class="meta" id="head">—</span></div><dl class="kv"><dt>Product</dt><dd><span id="product-name">—</span> <span id="product-version">—</span></dd><dt>Profile</dt><dd id="profile-name">—</dd><dt>Worktree</dt><dd id="project-path">—</dd><dt>Operator</dt><dd id="operator">—</dd><dt>Authority</dt><dd id="authority-summary">—</dd><dt>Transaction</dt><dd id="transaction-summary">—</dd></dl></article>
<article class="panel span-6"><div class="panel-title"><h2>Execution policy</h2><span class="meta">shared operator policy</span></div><dl class="kv"><dt>Provider</dt><dd id="provider">—</dd><dt>Model</dt><dd id="policy-model">—</dd><dt>Effort</dt><dd id="policy-effort">—</dd><dt>Efficiency</dt><dd id="efficiency">—</dd><dt>Reserve</dt><dd id="reserve">—</dd><dt>Wait limits</dt><dd id="wait-limits">—</dd><dt>Usage poll</dt><dd id="usage-poll">—</dd><dt>Max loops</dt><dd id="max-loops">—</dd><dt>Reviewer</dt><dd id="policy-reviewer">—</dd><dt>Approved</dt><dd id="policy-approved">—</dd></dl></article>
<article class="panel span-12"><div class="panel-title"><h2>Change attribution</h2><span class="meta">display-only classification</span></div><div id="attribution" class="attribution"></div><div class="attribution-note"><strong>No automatic adoption or reattribution.</strong> External and unresolved paths require an explicit human decision before any future carry-forward action.</div></article>
<article class="panel span-6"><div class="panel-title"><h2>Evidence</h2><span class="meta">controller-owned · ignored</span></div><dl class="kv"><dt>Runtime directory</dt><dd id="runtime-directory">—</dd><dt>Runtime files</dt><dd id="runtime-count">0</dd><dt>Controller receipts</dt><dd id="controller-receipts">0</dd><dt>Source-tree fallback</dt><dd id="source-tree-fallback">—</dd><dt>Legacy delegate</dt><dd id="legacy-delegate">—</dd></dl><details><summary>Raw evidence summary</summary><pre id="evidence-json" class="evidence">{{}}</pre></details></article>
<article class="panel span-6"><div class="panel-title"><h2>Recent authority evidence</h2><span class="meta">latest human decisions</span></div><div id="authority-evidence" class="authority-evidence">No recent authority evidence.</div></article>
<article class="panel span-12"><div class="panel-title"><h2>Authority actions</h2><span class="meta">preview → exact confirmation</span></div><div class="action-grid">
<div class="action-card"><h3>Operator / adoption</h3><div class="field"><label for="operator-input">Named operator</label><input id="operator-input" autocomplete="off" placeholder="Operator name"></div><div class="field"><label for="dirty-evidence">Dirty recovery attestation path (dirty journeys only)</label><input id="dirty-evidence" autocomplete="off" placeholder="/path/to/attestation.json"></div><div class="field"><label for="preview-input">Exact adoption preview SHA-256</label><input id="preview-input" autocomplete="off"></div><div class="button-row"><button class="sn-btn sn-btn--secondary" onclick="stygnoxAction('adopt.preview')">Preview adoption</button><button class="sn-btn warn" onclick="stygnoxAction('adopt.abort')">Abort preview</button><button class="sn-btn sn-btn--primary" onclick="stygnoxAction('adopt.handoff')">Confirm handoff</button></div></div>
<div class="action-card"><h3>Execution policy</h3><div class="field"><label for="policy-provider">Provider</label><input id="policy-provider" autocomplete="off" placeholder="neutral / codex"></div><div class="field"><label for="policy-model-input">Model</label><input id="policy-model-input" autocomplete="off" placeholder="neutral / model name"></div><div class="field"><label for="policy-effort-input">Effort</label><input id="policy-effort-input" autocomplete="off" placeholder="neutral / high"></div><div class="field"><label for="policy-reviewer">Reviewer</label><input id="policy-reviewer" autocomplete="off" placeholder="Required for non-neutral policy"></div><div class="field"><label for="policy-efficiency">Efficiency mode</label><select id="policy-efficiency"><option value="">leave unchanged</option><option>STRICT</option><option>NORMAL</option><option>RELAXED</option><option>OFF</option></select></div><div class="field"><label for="policy-reserve">Reserve percent</label><input id="policy-reserve" inputmode="decimal" autocomplete="off"></div><div class="field"><label for="policy-wait">Wait for limits</label><select id="policy-wait"><option value="">leave unchanged</option><option value="true">true</option><option value="false">false</option></select></div><div class="field"><label for="policy-poll">Usage poll seconds</label><input id="policy-poll" inputmode="numeric" autocomplete="off"></div><div class="field"><label for="policy-loops">Max loops</label><input id="policy-loops" inputmode="numeric" autocomplete="off"></div><div class="field"><label for="policy-preview-input">Exact policy preview SHA-256</label><input id="policy-preview-input" autocomplete="off"></div><div class="button-row"><button class="sn-btn sn-btn--secondary" onclick="stygnoxAction('policy.preview')">Preview policy</button><button class="sn-btn sn-btn--primary" onclick="stygnoxAction('policy.set')">Apply policy</button><button class="sn-btn sn-btn--secondary" onclick="stygnoxAction('policy.preview-reset')">Preview reset</button><button class="sn-btn warn" onclick="stygnoxAction('policy.reset')">Reset neutral</button></div></div>
<div class="action-card"><h3>Transaction / recovery</h3><div class="field"><label for="stop-reason">Safe-stop reason</label><select id="stop-reason"><option>operator-abort</option><option>interrupted</option><option>authority-revoked</option><option>qualification</option></select></div><div class="field"><label for="recovery-preview-input">Exact recovery preview SHA-256</label><input id="recovery-preview-input" autocomplete="off"></div><div class="button-row"><button class="sn-btn sn-btn--primary" onclick="stygnoxAction('transaction.begin')">Begin transaction</button><button class="sn-btn warn" onclick="stygnoxAction('transaction.stop')">Safe stop</button><button class="sn-btn sn-btn--secondary" onclick="stygnoxAction('recovery.preview')">Preview recovery</button><button class="sn-btn danger" onclick="stygnoxAction('recovery.restore')">Restore baseline</button></div></div>
<div class="action-card"><h3>Controller authority</h3><div class="field"><label for="objective">One-turn objective</label><textarea id="objective" placeholder="Bounded implementation objective"></textarea></div><div class="field"><label for="repo-authority">Repository authority</label><select id="repo-authority"><option value="read-only">read-only</option><option value="write">write</option></select></div><div class="field"><label for="run-preview-input">Exact run preview SHA-256</label><input id="run-preview-input" autocomplete="off"></div><div class="button-row"><button class="sn-btn sn-btn--primary" onclick="stygnoxAction('controller.activate')">Activate</button><button class="sn-btn sn-btn--secondary" onclick="stygnoxAction('controller.run-preview')">Preview run</button><button class="sn-btn sn-btn--primary" onclick="stygnoxAction('controller.run')">Run confirmed turn</button><button class="sn-btn warn" onclick="stygnoxAction('controller.deactivate')">Deactivate</button></div></div>
<div class="action-card"><h3>Action evidence</h3><div id="notice" class="notice" role="status" aria-live="polite"></div><pre id="action-result" class="evidence" aria-label="Latest action result">No action yet.</pre></div>
</div></article></section>
<footer class="footer"><span>Stygnox · Plan · Execute · Evidence · Evolve</span><span>Web and TUI share installed operator semantics</span></footer></main><script src="/assets/operator.js"></script></body></html>'''
    return page.encode("utf-8")

def _login_html(error: str = "") -> bytes:
    error_html = f'<div class="notice danger" role="alert">{error}</div>' if error else ""
    page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Stygnox Login</title><link rel="icon" href="/assets/stygnox-icon-128.png"><link rel="stylesheet" href="/assets/design-tokens.css"><link rel="stylesheet" href="/assets/components.css"><link rel="stylesheet" href="/assets/operator.css"></head>
<body><main class="operator-shell operator-main"><section class="sn-panel sn-panel--glow hero-panel"><div class="hero-copy"><div class="section-kicker">Operator authentication</div><h1>Sign in to Stygnox.</h1><p>Use the operator credentials configured with <code>stygnox web-auth set</code>.</p></div><img class="hero-logo" src="/assets/stygnox-logo-800x300.png" alt="Stygnox"></section>
<section class="operator-grid"><article class="panel span-5"><div class="panel-title"><h2>Operator login</h2></div>{error_html}<form method="post" action="/login"><div class="field"><label for="username">Username</label><input id="username" name="username" autocomplete="username" required autofocus></div><div class="field"><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required></div><div class="button-row"><button class="sn-btn sn-btn--primary" type="submit">Sign in</button></div></form></article></section></main></body></html>'''
    return page.encode("utf-8")


def _auth_record_path(root: Path) -> Path:
    return root / adoption.RUNTIME_NAME / WEB_AUTH_RECORD


def _validate_username(value: str) -> str:
    username = str(value or "").strip()
    if not username or len(username) > 128 or ":" in username or any(ord(ch) < 32 for ch in username):
        raise WebError("Web username must be 1-128 printable characters and must not contain ':'")
    return username


def _password_digest(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def load_web_auth(project: Path) -> tuple[Path, dict[str, Any] | None]:
    root = adoption.resolve_worktree(project)
    path = _auth_record_path(root)
    if not path.exists():
        return root, None
    if path.is_symlink() or not path.is_file():
        raise WebError("Web authentication record must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WebError(f"invalid Web authentication record: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != WEB_AUTH_SCHEMA:
        raise WebError("unsupported Web authentication record")
    username = _validate_username(str(value.get("username") or ""))
    try:
        iterations = int(value.get("iterations"))
        salt = bytes.fromhex(str(value.get("salt_hex") or ""))
        digest = bytes.fromhex(str(value.get("password_digest_hex") or ""))
    except (TypeError, ValueError) as exc:
        raise WebError("invalid Web authentication record") from exc
    if iterations < 100_000 or len(salt) < 16 or len(digest) != hashlib.sha256().digest_size:
        raise WebError("invalid Web authentication record")
    return root, {
        "schema": WEB_AUTH_SCHEMA,
        "username": username,
        "iterations": iterations,
        "salt_hex": salt.hex(),
        "password_digest_hex": digest.hex(),
    }


def set_web_auth(project: Path, username: str, password: str) -> Path:
    root = adoption.resolve_worktree(project)
    name = _validate_username(username)
    if not password:
        raise WebError("Web password must not be empty")
    salt = secrets.token_bytes(16)
    record = {
        "schema": WEB_AUTH_SCHEMA,
        "product_version": PRODUCT.version,
        "username": name,
        "iterations": WEB_AUTH_ITERATIONS,
        "salt_hex": salt.hex(),
        "password_digest_hex": _password_digest(password, salt, WEB_AUTH_ITERATIONS).hex(),
    }
    return adoption.write_runtime_record(root, WEB_AUTH_RECORD, record, actor="controller")


def clear_web_auth(project: Path) -> bool:
    root = adoption.resolve_worktree(project)
    path = _auth_record_path(root)
    if not path.exists():
        return False
    if path.is_symlink() or not path.is_file():
        raise WebError("Web authentication record must be a regular file")
    path.unlink()
    return True


def _credentials_match(record: dict[str, Any] | None, username: str, password: str) -> bool:
    if record is None:
        return True
    try:
        salt = bytes.fromhex(str(record["salt_hex"]))
        expected = bytes.fromhex(str(record["password_digest_hex"]))
        actual = _password_digest(password, salt, int(record["iterations"]))
    except (ValueError, KeyError, TypeError):
        return False
    return hmac.compare_digest(username, str(record["username"])) and hmac.compare_digest(actual, expected)


def _authorization_matches(record: dict[str, Any] | None, header: str | None) -> bool:
    if record is None:
        return True
    if not header or not header.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
        username, password = raw.split(":", 1)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    return _credentials_match(record, username, password)


def _remote_bind_allowed(host: str, auth_record: dict[str, Any] | None) -> bool:
    return _loopback(host) or auth_record is not None


class OperatorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], project: Path, *, auth_record: dict[str, Any] | None = None):
        self.project = adoption.resolve_worktree(project)
        self.csrf = secrets.token_urlsafe(32)
        self.auth_record = auth_record
        self.sessions: set[str] = set()
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server: OperatorServer

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet deterministic local console
        return

    def _session_token(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return None
        morsel = cookie.get("StygnoxSession")
        return morsel.value if morsel is not None else None

    def _authorized(self) -> bool:
        if self.server.auth_record is None:
            return True
        if _authorization_matches(self.server.auth_record, self.headers.get("Authorization")):
            return True
        token = self._session_token()
        return bool(token and token in self.server.sessions)

    def _authentication_required(self) -> None:
        body = b"Stygnox Web authentication required\n"
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="Stygnox", charset="UTF-8"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str, *, cookie: str | None = None) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

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
            if path.startswith("/assets/"):
                name = path.removeprefix("/assets/")
                content_type = "text/css; charset=utf-8" if name.endswith(".css") else "application/javascript; charset=utf-8" if name.endswith(".js") else "image/png"
                self._bytes(HTTPStatus.OK, _asset(name), content_type)
                return
            if path == "/login":
                if self._authorized():
                    self._redirect("/")
                else:
                    self._bytes(HTTPStatus.OK, _login_html(), "text/html; charset=utf-8")
                return
            if path == "/logout":
                token = self._session_token()
                if token:
                    self.server.sessions.discard(token)
                self._redirect("/login", cookie="StygnoxSession=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
                return
            if not self._authorized():
                if path == "/":
                    self._bytes(HTTPStatus.OK, _login_html(), "text/html; charset=utf-8")
                else:
                    self._authentication_required()
                return
            if path == "/":
                self._bytes(HTTPStatus.OK, _index_html(self.server.csrf), "text/html; charset=utf-8")
                return
            if path == "/health":
                self._json(HTTPStatus.OK, {"ok": True, "product": PRODUCT.name, "version": PRODUCT.version})
                return
            if path == "/api/snapshot":
                self._json(HTTPStatus.OK, operator_snapshot(self.server.project, server_pid=self.server.server_address[1] and __import__('os').getpid()))
                return
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "unsupported Web route"})
        except (WebError, OperatorSurfaceError, adoption.AdoptionError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/login":
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                size = 0
            if size < 1 or size > 16 * 1024:
                self._bytes(HTTPStatus.BAD_REQUEST, _login_html("Invalid login request."), "text/html; charset=utf-8")
                return
            try:
                fields = parse_qs(self.rfile.read(size).decode("utf-8"), keep_blank_values=True)
                username = fields.get("username", [""])[0]
                password = fields.get("password", [""])[0]
            except UnicodeDecodeError:
                username = password = ""
            if not _credentials_match(self.server.auth_record, username, password):
                self._bytes(HTTPStatus.UNAUTHORIZED, _login_html("Invalid username or password."), "text/html; charset=utf-8")
                return
            token = secrets.token_urlsafe(32)
            self.server.sessions.add(token)
            self._redirect("/", cookie=f"StygnoxSession={token}; Path=/; HttpOnly; SameSite=Strict")
            return
        if not self._authorized():
            self._authentication_required()
            return
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
    parser.add_argument("--host", default="127.0.0.1", help="bind address; non-loopback binds require configured Web authentication")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    import sys
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        root, auth_record = load_web_auth(args.project)
    except (WebError, adoption.AdoptionError) as exc:
        print(f"stygnox: web refused: {exc}", file=sys.stderr)
        return 2
    if not _remote_bind_allowed(args.host, auth_record):
        print("stygnox: web refused: non-loopback binding requires credentials; run 'stygnox web-auth set --username <name>' first", file=sys.stderr)
        return 2
    try:
        server = OperatorServer((args.host, args.port), root, auth_record=auth_record)
    except (OSError, adoption.AdoptionError) as exc:
        print(f"stygnox: web refused: {exc}", file=sys.stderr)
        return 2
    host, port = server.server_address[:2]
    print(f"Stygnox Web {PRODUCT.version} · http://{host}:{port} · project={server.project} · auth={'required' if auth_record else 'off'}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def build_auth_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stygnox web-auth", description="Configure simple username/password authentication for Stygnox Web.")
    sub = parser.add_subparsers(dest="action", required=True)
    configure = sub.add_parser("set", help="set or replace the Web username/password")
    configure.add_argument("--username", required=True)
    configure.add_argument("--project", type=Path, default=Path.cwd(), help="Git worktree")
    status = sub.add_parser("status", help="show whether Web authentication is configured")
    status.add_argument("--project", type=Path, default=Path.cwd(), help="Git worktree")
    clear = sub.add_parser("clear", help="remove configured Web authentication")
    clear.add_argument("--project", type=Path, default=Path.cwd(), help="Git worktree")
    return parser


def auth_cli_main(argv: Sequence[str] | None = None) -> int:
    import sys
    args = build_auth_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "set":
            password = getpass.getpass("Stygnox Web password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                print("stygnox: web-auth refused: passwords do not match", file=sys.stderr)
                return 2
            path = set_web_auth(args.project, args.username, password)
            print(f"Stygnox Web authentication configured · username={_validate_username(args.username)} · record={path}")
            return 0
        if args.action == "status":
            root, record = load_web_auth(args.project)
            if record is None:
                print(f"Stygnox Web authentication not configured · project={root}")
            else:
                print(f"Stygnox Web authentication configured · username={record['username']} · project={root}")
            return 0
        if args.action == "clear":
            removed = clear_web_auth(args.project)
            root = adoption.resolve_worktree(args.project)
            print(f"Stygnox Web authentication {'cleared' if removed else 'not configured'} · project={root}")
            return 0
    except (WebError, adoption.AdoptionError, OSError) as exc:
        print(f"stygnox: web-auth refused: {exc}", file=sys.stderr)
        return 2
    return 2
