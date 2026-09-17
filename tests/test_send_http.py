# MIT License
"""Direct Send-to-Epika HTTP handler tests without sockets."""

from __future__ import annotations

import inspect
import json
from base64 import urlsafe_b64encode
from pathlib import Path

import pytest

from resources.lib.send_http import (
    Clock,
    Deduper,
    DispatchError,
    DispatchJob,
    HttpRequest,
    RateLimiter,
    SendHttpApp,
    handle_http,
    token_digest,
    token_is_valid,
)
from resources.lib.send_reference import (
    EpikaUnavailableError,
    NotFoundError,
    ResolvedReference,
    UnsupportedProductError,
    UnsupportedUrlError,
    resolve_epika_url,
)
from resources.lib import send_http as send_http_mod
from tests.test_send_reference import EPISODE_URL, SEASON_URL, SERIAL_URL, VOD_URL, ScriptedLookup

TOKEN = urlsafe_b64encode(b"A" * 32).decode("ascii").rstrip("=")
FIXTURES = Path(__file__).parent / "fixtures"


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Recorder:
    def __init__(self):
        self.jobs = []
        self.logs = []
        self.accepting = True
        self.error = None

    def dispatch(self, job: DispatchJob) -> None:
        self.jobs.append(job)
        if self.error is not None:
            raise self.error

    def log(self, level: str, **fields) -> None:
        self.logs.append((level, fields))

    def is_accepting(self) -> bool:
        return self.accepting


def resolved(url: str) -> ResolvedReference:
    return resolve_epika_url(url, ScriptedLookup())


def make_app(recorder=None, clock=None, resolver=None):
    recorder = recorder or Recorder()
    clock = clock or FakeClock()
    return SendHttpApp(
        token_digest=token_digest(TOKEN),
        resolver=resolver or (lambda url: resolved(url)),
        dispatcher=recorder.dispatch,
        limiter=RateLimiter(clock),
        deduper=Deduper(clock),
        clock=clock,
        log=recorder.log,
        is_accepting=recorder.is_accepting,
        version="0.2.1",
    ), recorder, clock


def call(
    app,
    method="POST",
    path="/v1/send",
    url=VOD_URL,
    body=None,
    headers=None,
    ip="127.0.0.1",
    token=TOKEN,
    content_type="application/json",
):
    if body is None and method == "POST":
        body = json.dumps({"url": url}).encode("utf-8")
    elif body is None:
        body = b""
    header_list = list(headers or [])
    names = {name.lower() for name, _value in header_list}
    if token is not None and "authorization" not in names:
        header_list.append(("Authorization", f"Bearer {token}"))
    if method == "POST" and "content-type" not in names and content_type is not None:
        header_list.append(("Content-Type", content_type))
    if "content-length" not in names:
        if method == "POST":
            header_list.append(("Content-Length", str(len(body))))
    request = HttpRequest(method=method, path=path, headers=header_list, body=body, client_ip=ip)
    response = handle_http(app, request)
    payload = json.loads(response.body.decode("utf-8"))
    return response, payload


def test_token_requires_32_urlsafe_bytes():
    assert token_is_valid(TOKEN)
    assert not token_is_valid("")
    assert not token_is_valid("short")
    assert not token_is_valid(urlsafe_b64encode(b"A" * 31).decode("ascii").rstrip("="))
    assert not token_is_valid(TOKEN + "+/not")


def test_send_and_health_success():
    app, recorder, _clock = make_app()
    response, payload = call(app)
    assert response.status == 202
    assert payload["ok"] is True
    assert payload["action"] == "play"
    assert payload["duplicate"] is False
    assert payload["product"] == {"id": 432486, "kind": "vod", "title": "Adomas nori būti žmogumi"}
    assert payload["requestId"]
    assert recorder.jobs[0].plugin_url.endswith("route=play&product_id=432486&item_type=VOD")
    header_map = {name: value for name, value in response.all_headers}
    assert header_map["Content-Type"] == "application/json"
    assert header_map["Cache-Control"] == "no-store"
    assert "Access-Control-Allow-Origin" not in header_map

    response, payload = call(app, method="GET", path="/v1/health")
    assert response.status == 200
    assert payload == {"ok": True, "service": "lrtepika-send", "version": "0.2.1"}


def test_four_kinds_dispatch_actions():
    app, recorder, _clock = make_app()
    _, vod = call(app, url=VOD_URL)
    _, serial = call(app, url=SERIAL_URL, ip="10.0.0.2")
    _, episode = call(app, url=EPISODE_URL, ip="10.0.0.3")
    _, season = call(app, url=SEASON_URL, ip="10.0.0.4")
    assert [item["action"] for item in (vod, serial, episode, season)] == [
        "play",
        "browse",
        "play",
        "browse",
    ]
    assert [job.kind for job in recorder.jobs] == ["VOD", "SERIAL", "EPISODE", "SEASON"]
    assert recorder.jobs[1].plugin_url.startswith("plugin://plugin.video.lrtepika/?route=serial")
    assert "route=episodes" in recorder.jobs[3].plugin_url


def test_auth_failures_are_constant_401():
    app, recorder, _clock = make_app()
    cases = [
        call(app, token=None, headers=[]),
        call(app, token="nope"),
        call(app, headers=[("Authorization", f"Bearer {TOKEN}"), ("Authorization", f"Bearer {TOKEN}")]),
        call(app, headers=[("Authorization", TOKEN)]),
        call(app, headers=[("Authorization", f"bearer {TOKEN}")]),
        call(app, headers=[("Authorization", "Bearer " + ("A" * 300))]),
    ]
    for response, payload in cases:
        assert response.status == 401
        assert payload["error"] == "unauthorized"
        assert payload["ok"] is False
        assert "requestId" in payload
        assert set(payload.keys()) == {"ok", "requestId", "error"}
    assert recorder.jobs == []


def test_malformed_and_unsupported_status_mapping():
    app, recorder, _clock = make_app()
    response, payload = call(app, body=b"{", headers=[("Content-Type", "application/json")], ip="10.0.1.1")
    assert response.status == 400
    assert payload["error"] == "invalid_json"

    missing_length = handle_http(
        app,
        HttpRequest(
            method="POST",
            path="/v1/send",
            headers=[("Authorization", f"Bearer {TOKEN}"), ("Content-Type", "application/json")],
            body=b'{"url":"https://epika.lrt.lt/x,1"}',
            client_ip="10.0.1.2",
        ),
    )
    assert missing_length.status == 400

    response, payload = call(
        app, body=json.dumps({"url": VOD_URL, "id": 1}).encode(), ip="10.0.1.3"
    )
    assert response.status == 400
    assert payload["error"] == "invalid_request"

    response, payload = call(app, body=json.dumps({"id": 432486}).encode(), ip="10.0.1.4")
    assert response.status == 400

    response, payload = call(app, method="GET", path="/v1/send")
    assert response.status == 405
    assert dict(response.all_headers)["Allow"] == "POST"

    response, payload = call(app, method="POST", path="/v1/health", body=b"{}", ip="10.0.1.5")
    assert response.status == 405
    assert dict(response.all_headers)["Allow"] == "GET"

    response, payload = call(app, method="OPTIONS", path="/v1/send")
    assert response.status == 405

    response, payload = call(app, body=b"x" * 2049, ip="10.0.1.6")
    assert response.status == 413

    response, payload = call(app, content_type="text/plain", ip="10.0.1.7")
    assert response.status == 415

    response, payload = call(app, content_type="application/json; charset=latin-1", ip="10.0.1.8")
    assert response.status == 415

    response, payload = call(app, body=b"\xff\xfe{}", content_type="application/json", ip="10.0.1.9")
    assert response.status == 415

    response, payload = call(app, url="https://example.invalid/x,1", ip="10.0.1.10")
    assert response.status == 422
    assert payload["error"] == "unsupported_url"


def test_forbidden_headers_and_query_are_rejected():
    app, _recorder, _clock = make_app()
    for header in (("Origin", "https://evil.example"), ("Transfer-Encoding", "chunked"), ("Expect", "100-continue")):
        response, payload = call(app, headers=[header])
        assert response.status == 400
        assert payload["error"] == "invalid_request"

    response, payload = call(app, path="/v1/send?x=1")
    assert response.status == 400

    response, payload = call(
        app,
        headers=[("Content-Type", "application/json"), ("Content-Type", "text/plain")],
    )
    assert response.status == 400


def test_resolver_status_mapping():
    def raiser(exc):
        def _resolve(_url):
            raise exc

        return _resolve

    app, recorder, _clock = make_app(resolver=raiser(NotFoundError()))
    response, payload = call(app)
    assert response.status == 404
    assert payload["error"] == "not_found"

    app, recorder, _clock = make_app(resolver=raiser(UnsupportedProductError()))
    response, payload = call(app)
    assert response.status == 422
    assert payload["error"] == "unsupported_product"

    app, recorder, _clock = make_app(resolver=raiser(EpikaUnavailableError()))
    response, payload = call(app)
    assert response.status == 502
    assert payload["error"] == "epika_unavailable"
    assert recorder.jobs == []


def test_rate_limit_per_ip_uses_injected_clock():
    clock = FakeClock()
    app, recorder, clock = make_app(clock=clock)
    for url in (VOD_URL, SERIAL_URL, EPISODE_URL):
        response, _payload = call(app, url=url)
        assert response.status == 202
    response, payload = call(app, url=SEASON_URL)
    assert response.status == 429
    assert payload["error"] == "rate_limited"
    assert len(recorder.jobs) == 3
    clock.advance(12)
    response, payload = call(app, url=SEASON_URL)
    assert response.status == 202
    assert payload["duplicate"] is False
    assert len(recorder.jobs) == 4


def test_dedupe_returns_original_without_dispatch():
    clock = FakeClock()
    app, recorder, clock = make_app(clock=clock)
    response, first = call(app, url=VOD_URL)
    assert response.status == 202
    response, second = call(app, url=VOD_URL)
    assert response.status == 202
    assert second["duplicate"] is True
    assert second["requestId"] == first["requestId"]
    assert second["action"] == "play"
    assert len(recorder.jobs) == 1
    clock.advance(10.1)
    response, third = call(app, url=VOD_URL)
    assert response.status == 202
    assert third["duplicate"] is False
    assert third["requestId"] != first["requestId"]
    assert len(recorder.jobs) == 2


def test_global_rate_limit_across_ips():
    clock = FakeClock()
    app, recorder, clock = make_app(clock=clock)
    statuses = []
    for index in range(21):
        response, _payload = call(app, ip=f"10.0.0.{index + 1}", url=VOD_URL)
        statuses.append(response.status)
    assert statuses.count(202) == 20
    assert statuses[-1] == 429


def test_stopping_queue_and_dispatch_failure_are_503():
    recorder = Recorder()
    recorder.accepting = False
    app, recorder, _clock = make_app(recorder=recorder)
    response, payload = call(app)
    assert response.status == 503
    assert payload["error"] == "service_unavailable"

    recorder = Recorder()
    recorder.error = DispatchError("queue_full")
    app, recorder, _clock = make_app(recorder=recorder)
    response, payload = call(app)
    assert response.status == 503

    recorder = Recorder()
    recorder.error = DispatchError("failed")
    app, recorder, _clock = make_app(recorder=recorder)
    response, payload = call(app)
    assert response.status == 503


def test_logs_redact_secrets_headers_bodies_and_urls():
    app, recorder, _clock = make_app()
    call(app, url=VOD_URL)
    call(app, token="wrong-token")
    joined = json.dumps(recorder.logs)
    assert TOKEN not in joined
    assert "wrong-token" not in joined
    assert "Authorization" not in joined
    assert VOD_URL not in joined
    assert "adomas-nori-buti-zmogumi" not in joined
    assert "WIDEVINE" not in joined
    fields = recorder.logs[0][1]
    assert fields["status"] == 202
    assert fields["product_id"] == 432486
    assert fields["kind"] == "VOD"
    assert "url" not in fields
    assert "token" not in fields


def test_module_does_not_use_threading_server():
    source = inspect.getsource(send_http_mod)
    assert "ThreadingHTTPServer" not in source
    assert "HTTPServer" in source
