# MIT License
"""Authenticated Send-to-Epika HTTP contract. No sockets required to test."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from base64 import urlsafe_b64decode
from binascii import Error as BinasciiError
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from resources.lib.send_reference import (
    EpikaUnavailableError,
    NotFoundError,
    ResolvedReference,
    SendReferenceError,
    UnsupportedProductError,
    UnsupportedUrlError,
    resolve_epika_url,
)

SERVICE_NAME = "lrtepika-send"
SERVICE_VERSION = "0.2.0"
MAX_BODY_BYTES = 2048
MAX_AUTH_BYTES = 256
MIN_TOKEN_BYTES = 32
MAX_TOKEN_CHARS = 128
SOCKET_TIMEOUT = 5
DISPATCH_WAIT_SECONDS = 5.0
IP_BURST = 3
IP_RATE_PER_SEC = 5.0 / 60.0
GLOBAL_BURST = 20
GLOBAL_RATE_PER_SEC = 20.0 / 60.0
DEDUPE_TTL_SECONDS = 10.0
MAX_IP_BUCKETS = 256
JSON_HEADERS = (
    ("Content-Type", "application/json"),
    ("Cache-Control", "no-store"),
    ("X-Content-Type-Options", "nosniff"),
    ("Connection", "close"),
)
SENSITIVE_SINGLETONS = (
    "content-type",
    "content-length",
    "host",
    "origin",
    "transfer-encoding",
    "expect",
)
FORBIDDEN_HEADERS = ("transfer-encoding", "expect", "origin")
REDACT_FIELD_NAMES = {
    "authorization",
    "token",
    "url",
    "body",
    "cookie",
    "license",
    "header",
    "headers",
}


class DispatchError(Exception):
    def __init__(self, reason: str = "failed"):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class DispatchJob:
    request_id: str
    action: str
    plugin_url: str
    product_id: int
    kind: str
    title: str


@dataclass
class HttpRequest:
    method: str
    path: str
    headers: Sequence[tuple[str, str]]
    body: bytes
    client_ip: str


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = JSON_HEADERS
    extra_headers: tuple[tuple[str, str], ...] = ()

    @property
    def all_headers(self) -> tuple[tuple[str, str], ...]:
        return self.headers + self.extra_headers


class Clock:
    def time(self) -> float:
        import time

        return time.monotonic()


class RateLimiter:
    def __init__(
        self,
        clock: Clock,
        ip_burst: int = IP_BURST,
        ip_rate: float = IP_RATE_PER_SEC,
        global_burst: int = GLOBAL_BURST,
        global_rate: float = GLOBAL_RATE_PER_SEC,
    ):
        self.clock = clock
        self.ip_burst = ip_burst
        self.ip_rate = ip_rate
        self.global_burst = global_burst
        self.global_rate = global_rate
        self._ips: dict[str, tuple[float, float]] = {}
        self._global = (float(global_burst), 0.0)

    def allow(self, client_ip: str) -> bool:
        now = self.clock.time()
        if not self._consume(now, True, client_ip):
            return False
        if not self._consume(now, False, client_ip):
            self._refund_ip(now, client_ip)
            return False
        return True

    def _consume(self, now: float, per_ip: bool, client_ip: str) -> bool:
        if per_ip:
            tokens, last = self._ips.get(client_ip, (float(self.ip_burst), now))
            burst, rate = self.ip_burst, self.ip_rate
        else:
            tokens, last = self._global
            burst, rate = self.global_burst, self.global_rate
        tokens = min(float(burst), tokens + max(0.0, now - last) * rate)
        if tokens < 1.0:
            if per_ip:
                self._ips[client_ip] = (tokens, now)
            else:
                self._global = (tokens, now)
            return False
        tokens -= 1.0
        if per_ip:
            self._prune_ips(now)
            self._ips[client_ip] = (tokens, now)
        else:
            self._global = (tokens, now)
        return True

    def _refund_ip(self, now: float, client_ip: str) -> None:
        tokens, _last = self._ips.get(client_ip, (0.0, now))
        self._ips[client_ip] = (min(float(self.ip_burst), tokens + 1.0), now)

    def _prune_ips(self, now: float) -> None:
        if len(self._ips) < MAX_IP_BUCKETS:
            return
        stale = [ip for ip, (_tokens, last) in self._ips.items() if now - last > 60.0]
        for ip in stale:
            self._ips.pop(ip, None)
        if len(self._ips) < MAX_IP_BUCKETS:
            return
        oldest = sorted(self._ips.items(), key=lambda item: item[1][1])
        for ip, _bucket in oldest[: max(1, len(oldest) // 8)]:
            self._ips.pop(ip, None)


class Deduper:
    def __init__(self, clock: Clock, ttl: float = DEDUPE_TTL_SECONDS):
        self.clock = clock
        self.ttl = ttl
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}

    def lookup(self, key: str) -> dict[str, Any] | None:
        now = self.clock.time()
        self._purge(now)
        item = self._items.get(key)
        if item is None:
            return None
        expires, payload = item
        if expires <= now:
            self._items.pop(key, None)
            return None
        return payload

    def remember(self, key: str, payload: dict[str, Any]) -> None:
        self._items[key] = (self.clock.time() + self.ttl, payload)

    def _purge(self, now: float) -> None:
        expired = [key for key, (expires, _payload) in self._items.items() if expires <= now]
        for key in expired:
            self._items.pop(key, None)


@dataclass
class SendHttpApp:
    token_digest: bytes
    resolver: Callable[[str], ResolvedReference]
    dispatcher: Callable[[DispatchJob], None]
    limiter: RateLimiter
    deduper: Deduper
    clock: Clock
    log: Callable[..., None]
    is_accepting: Callable[[], bool]
    version: str = SERVICE_VERSION
    dispatch_timeout: float = DISPATCH_WAIT_SECONDS


def token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def token_is_valid(token: str) -> bool:
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_CHARS:
        return False
    if token.strip() != token:
        return False
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=")
    if any(char not in allowed for char in token):
        return False
    padded = token + ("=" * ((4 - len(token) % 4) % 4))
    try:
        raw = urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, BinasciiError):
        return False
    return len(raw) >= MIN_TOKEN_BYTES


def handle_http(app: SendHttpApp, request: HttpRequest) -> HttpResponse:
    started = app.clock.time()
    request_id = secrets.token_hex(4)
    client_ip = request.client_ip or "unknown"
    try:
        return _handle_http(app, request, request_id, client_ip, started)
    except Exception:
        _log(
            app,
            "error",
            request_id=request_id,
            client_ip=client_ip,
            status=500,
            latency_ms=_latency_ms(app, started),
            error="internal_error",
        )
        return _error(500, request_id, "internal_error")


def _handle_http(
    app: SendHttpApp,
    request: HttpRequest,
    request_id: str,
    client_ip: str,
    started: float,
) -> HttpResponse:
    method = (request.method or "").upper()
    path, query = _split_path(request.path)
    header_map = _header_map(request.headers)

    header_error = _reject_headers(header_map)
    if header_error is not None:
        status, code, extra = header_error
        _log(
            app,
            "warning",
            request_id=request_id,
            client_ip=client_ip,
            status=status,
            error=code,
            latency_ms=_latency_ms(app, started),
        )
        return _error(status, request_id, code, extra=extra)

    if query:
        _log(
            app,
            "warning",
            request_id=request_id,
            client_ip=client_ip,
            status=400,
            error="invalid_request",
            latency_ms=_latency_ms(app, started),
        )
        return _error(400, request_id, "invalid_request")

    if path == "/v1/send":
        allowed = "POST"
        if method != "POST":
            return _method_not_allowed(app, request_id, client_ip, started, allowed)
    elif path == "/v1/health":
        allowed = "GET"
        if method != "GET":
            return _method_not_allowed(app, request_id, client_ip, started, allowed)
    else:
        _log(
            app,
            "info",
            request_id=request_id,
            client_ip=client_ip,
            status=404,
            error="not_found",
            latency_ms=_latency_ms(app, started),
        )
        return _error(404, request_id, "not_found")

    auth_error = _authenticate(app, header_map)
    if auth_error is not None:
        _log(
            app,
            "warning",
            request_id=request_id,
            client_ip=client_ip,
            status=401,
            error="unauthorized",
            latency_ms=_latency_ms(app, started),
        )
        return _error(401, request_id, "unauthorized")

    if not app.limiter.allow(client_ip):
        _log(
            app,
            "warning",
            request_id=request_id,
            client_ip=client_ip,
            status=429,
            error="rate_limited",
            latency_ms=_latency_ms(app, started),
        )
        return _error(429, request_id, "rate_limited")

    if not app.is_accepting():
        _log(
            app,
            "warning",
            request_id=request_id,
            client_ip=client_ip,
            status=503,
            error="service_unavailable",
            latency_ms=_latency_ms(app, started),
        )
        return _error(503, request_id, "service_unavailable")

    length_error = _content_length_error(method, header_map, request.body)
    if length_error is not None:
        status, code = length_error
        _log(
            app,
            "warning",
            request_id=request_id,
            client_ip=client_ip,
            status=status,
            error=code,
            latency_ms=_latency_ms(app, started),
        )
        return _error(status, request_id, code)

    if path == "/v1/health":
        payload = {"ok": True, "service": SERVICE_NAME, "version": app.version}
        _log(
            app,
            "info",
            request_id=request_id,
            client_ip=client_ip,
            status=200,
            action="health",
            latency_ms=_latency_ms(app, started),
        )
        return _json(200, payload)

    media_error = _media_type_error(header_map)
    if media_error is not None:
        status, code = media_error
        _log(
            app,
            "warning",
            request_id=request_id,
            client_ip=client_ip,
            status=status,
            error=code,
            latency_ms=_latency_ms(app, started),
        )
        return _error(status, request_id, code)

    envelope = _parse_send_envelope(request.body)
    if isinstance(envelope, HttpResponse):
        _log(
            app,
            "warning",
            request_id=request_id,
            client_ip=client_ip,
            status=envelope.status,
            error=_error_code(envelope),
            latency_ms=_latency_ms(app, started),
        )
        return _with_request_id(envelope, request_id)

    try:
        resolved = app.resolver(envelope)
    except NotFoundError:
        _log(
            app,
            "info",
            request_id=request_id,
            client_ip=client_ip,
            status=404,
            error="not_found",
            latency_ms=_latency_ms(app, started),
        )
        return _error(404, request_id, "not_found")
    except UnsupportedUrlError:
        _log(
            app,
            "info",
            request_id=request_id,
            client_ip=client_ip,
            status=422,
            error="unsupported_url",
            latency_ms=_latency_ms(app, started),
        )
        return _error(422, request_id, "unsupported_url")
    except UnsupportedProductError:
        _log(
            app,
            "info",
            request_id=request_id,
            client_ip=client_ip,
            status=422,
            error="unsupported_product",
            latency_ms=_latency_ms(app, started),
        )
        return _error(422, request_id, "unsupported_product")
    except (EpikaUnavailableError, SendReferenceError) as exc:
        status = getattr(exc, "status", 502) or 502
        code = getattr(exc, "code", "epika_unavailable") or "epika_unavailable"
        if status not in (404, 422, 502):
            status, code = 502, "epika_unavailable"
        _log(
            app,
            "warning",
            request_id=request_id,
            client_ip=client_ip,
            status=status,
            error=code,
            latency_ms=_latency_ms(app, started),
        )
        return _error(status, request_id, code)

    dedupe_key = f"{resolved.kind}:{resolved.product_id}:{resolved.action}"
    previous = app.deduper.lookup(dedupe_key)
    if previous is not None:
        body = dict(previous)
        body["duplicate"] = True
        _log(
            app,
            "info",
            request_id=request_id,
            client_ip=client_ip,
            status=202,
            action=resolved.action,
            product_id=resolved.product_id,
            kind=resolved.kind,
            duplicate=True,
            latency_ms=_latency_ms(app, started),
        )
        return _json(202, body)

    job = DispatchJob(
        request_id=request_id,
        action=resolved.action,
        plugin_url=resolved.plugin_url,
        product_id=resolved.product_id,
        kind=resolved.kind,
        title=resolved.title,
    )
    try:
        app.dispatcher(job)
    except DispatchError as exc:
        _log(
            app,
            "warning",
            request_id=request_id,
            client_ip=client_ip,
            status=503,
            error="service_unavailable",
            reason=exc.reason,
            action=resolved.action,
            product_id=resolved.product_id,
            kind=resolved.kind,
            latency_ms=_latency_ms(app, started),
        )
        return _error(503, request_id, "service_unavailable")

    payload = {
        "ok": True,
        "requestId": request_id,
        "action": resolved.action,
        "duplicate": False,
        "product": {
            "id": resolved.product_id,
            "kind": resolved.wire_kind,
            "title": resolved.title,
        },
    }
    app.deduper.remember(dedupe_key, payload)
    _log(
        app,
        "info",
        request_id=request_id,
        client_ip=client_ip,
        status=202,
        action=resolved.action,
        product_id=resolved.product_id,
        kind=resolved.kind,
        latency_ms=_latency_ms(app, started),
    )
    return _json(202, payload)


def default_resolver(api) -> Callable[[str], ResolvedReference]:
    def _resolve(url: str) -> ResolvedReference:
        return resolve_epika_url(url, api)

    return _resolve


def _split_path(raw_path: str) -> tuple[str, str]:
    parts = urlsplit(raw_path or "")
    return parts.path, parts.query


def _header_map(headers: Sequence[tuple[str, str]]) -> dict[str, list[str]]:
    mapped: dict[str, list[str]] = {}
    for name, value in headers:
        if not isinstance(name, str):
            continue
        mapped.setdefault(name.lower(), []).append("" if value is None else str(value))
    return mapped


def _reject_headers(
    header_map: Mapping[str, list[str]],
) -> tuple[int, str, tuple[tuple[str, str], ...]] | None:
    for name in FORBIDDEN_HEADERS:
        if header_map.get(name):
            return 400, "invalid_request", ()
    for name in SENSITIVE_SINGLETONS:
        values = header_map.get(name) or []
        if len(values) > 1:
            return 400, "invalid_request", ()
    return None


def _authenticate(app: SendHttpApp, header_map: Mapping[str, list[str]]) -> str | None:
    values = header_map.get("authorization") or []
    if len(values) != 1:
        return "unauthorized"
    raw = values[0]
    if len(raw.encode("utf-8")) > MAX_AUTH_BYTES or len(raw) > MAX_AUTH_BYTES:
        return "unauthorized"
    if not raw.startswith("Bearer "):
        return "unauthorized"
    token = raw[7:]
    if not token or " " in token:
        return "unauthorized"
    presented = token_digest(token)
    if not hmac.compare_digest(app.token_digest, presented):
        return "unauthorized"
    return None


def _content_length_error(
    method: str,
    header_map: Mapping[str, list[str]],
    body: bytes,
) -> tuple[int, str] | None:
    values = header_map.get("content-length") or []
    if method == "POST":
        if len(values) != 1:
            return 400, "invalid_request"
        raw = values[0].strip()
        if not raw.isdigit() or raw != str(int(raw)):
            return 400, "invalid_request"
        length = int(raw)
        if length > MAX_BODY_BYTES:
            return 413, "payload_too_large"
        if length != len(body):
            return 400, "invalid_request"
        return None
    if values:
        raw = values[0].strip()
        if not raw.isdigit():
            return 400, "invalid_request"
        if int(raw) != 0 or body:
            return 400, "invalid_request"
    elif body:
        return 400, "invalid_request"
    return None


def _media_type_error(header_map: Mapping[str, list[str]]) -> tuple[int, str] | None:
    values = header_map.get("content-type") or []
    if len(values) != 1:
        return 415, "unsupported_media_type"
    mime, charset = _split_content_type(values[0])
    if mime != "application/json":
        return 415, "unsupported_media_type"
    if charset not in (None, "utf-8"):
        return 415, "unsupported_media_type"
    return None


def _split_content_type(value: str) -> tuple[str, str | None]:
    parts = [item.strip() for item in value.split(";")]
    mime = (parts[0] if parts else "").lower()
    charset = None
    for item in parts[1:]:
        lowered = item.lower()
        if lowered.startswith("charset="):
            charset = item.split("=", 1)[1].strip().strip('"').lower()
    return mime, charset


def _parse_send_envelope(body: bytes) -> str | HttpResponse:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return _error(415, "pending", "unsupported_media_type")
    if text.startswith("\ufeff"):
        return _error(400, "pending", "invalid_json")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _error(400, "pending", "invalid_json")
    if not isinstance(data, dict):
        return _error(400, "pending", "invalid_json")
    if set(data.keys()) != {"url"}:
        return _error(400, "pending", "invalid_request")
    url = data.get("url")
    if not isinstance(url, str):
        return _error(400, "pending", "invalid_request")
    return url


def _method_not_allowed(
    app: SendHttpApp,
    request_id: str,
    client_ip: str,
    started: float,
    allowed: str,
) -> HttpResponse:
    _log(
        app,
        "info",
        request_id=request_id,
        client_ip=client_ip,
        status=405,
        error="method_not_allowed",
        latency_ms=_latency_ms(app, started),
    )
    return _error(405, request_id, "method_not_allowed", extra=(("Allow", allowed),))


def _error(
    status: int,
    request_id: str,
    code: str,
    extra: tuple[tuple[str, str], ...] = (),
) -> HttpResponse:
    return _json(status, {"ok": False, "requestId": request_id, "error": code}, extra=extra)


def _json(
    status: int,
    payload: dict[str, Any],
    extra: tuple[tuple[str, str], ...] = (),
) -> HttpResponse:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return HttpResponse(status=status, body=body, extra_headers=extra)


def _with_request_id(response: HttpResponse, request_id: str) -> HttpResponse:
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return response
    if not isinstance(payload, dict):
        return response
    payload["requestId"] = request_id
    return _json(response.status, payload, extra=response.extra_headers)


def _error_code(response: HttpResponse) -> str:
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return "invalid_request"
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        return payload["error"]
    return "invalid_request"


def _latency_ms(app: SendHttpApp, started: float) -> int:
    return int(max(0.0, (app.clock.time() - started) * 1000.0))


def _log(app: SendHttpApp, level: str, **fields: Any) -> None:
    safe = {key: value for key, value in fields.items() if key.lower() not in REDACT_FIELD_NAMES}
    try:
        app.log(level, **safe)
    except Exception:
        return


class SendHTTPRequestHandler(BaseHTTPRequestHandler):
    timeout = SOCKET_TIMEOUT
    protocol_version = "HTTP/1.1"
    close_connection = True

    def version_string(self) -> str:
        return SERVICE_NAME

    def log_message(self, format, *args):
        return

    def log_request(self, code="-", size="-"):
        return

    def log_error(self, format, *args):
        return

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_HEAD(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    def do_OPTIONS(self):
        self._handle()

    def do_PATCH(self):
        self._handle()

    def _handle(self) -> None:
        app: SendHttpApp = self.server.app
        headers = list(self.headers.items())
        header_map = _header_map(headers)
        body = b""
        try:
            if (header_map.get("transfer-encoding") or header_map.get("expect") or header_map.get("origin")):
                body = b""
            elif (self.command or "").upper() == "POST":
                values = header_map.get("content-length") or []
                if len(values) == 1 and values[0].strip().isdigit():
                    length = int(values[0].strip())
                    if 0 <= length <= MAX_BODY_BYTES:
                        body = self.rfile.read(length)
                    # oversized or invalid: do not read the body
            elif header_map.get("content-length"):
                raw = header_map["content-length"][0].strip()
                if raw.isdigit() and int(raw) == 0:
                    body = b""
            request = HttpRequest(
                method=self.command or "",
                path=self.path or "",
                headers=headers,
                body=body,
                client_ip=self.client_address[0] if self.client_address else "unknown",
            )
            response = handle_http(app, request)
        except Exception:
            response = _error(500, secrets.token_hex(4), "internal_error")
            try:
                app.log("error", status=500, error="internal_error")
            except Exception:
                pass
        self._write_response(response)

    def _write_response(self, response: HttpResponse) -> None:
        self.close_connection = True
        self.send_response(response.status)
        sent = set()
        for name, value in response.all_headers:
            self.send_header(name, value)
            sent.add(name.lower())
        if "content-length" not in sent:
            self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        if (self.command or "").upper() != "HEAD":
            self.wfile.write(response.body)
            try:
                self.wfile.flush()
            except Exception:
                pass


class SendHTTPServer(HTTPServer):
    allow_reuse_address = True
    timeout = 0.5

    def __init__(self, server_address, app: SendHttpApp):
        self.app = app
        super().__init__(server_address, SendHTTPRequestHandler)

    def handle_error(self, request, client_address):
        client_ip = client_address[0] if client_address else "unknown"
        try:
            self.app.log("error", client_ip=client_ip, error="handler_error")
        except Exception:
            return


def create_server(host: str, port: int, app: SendHttpApp) -> SendHTTPServer:
    return SendHTTPServer((host, port), app)
