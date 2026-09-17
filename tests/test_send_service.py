# MIT License
"""Send-to-Epika lifecycle, settings, and Kodi dispatch tests."""

from __future__ import annotations

import json
import socket
import threading
import time
from base64 import urlsafe_b64encode
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest

from resources.lib.send_http import DispatchJob, token_is_valid
from resources.lib.send_service import (
    ListenerSettings,
    SendRuntime,
    dispatch_to_kodi,
    read_kodi_settings,
    validate_bind_host,
    validate_port,
)
from resources.lib.send_reference import resolve_epika_url
from tests.conftest import FakeAddon, FakeMonitor, KODI
from tests.test_send_reference import VOD_URL, SERIAL_URL, SEASON_URL, ScriptedLookup

TOKEN = urlsafe_b64encode(b"B" * 32).decode("ascii").rstrip("=")


class MutableSettings:
    def __init__(self, current: ListenerSettings):
        self.current = current

    def __call__(self) -> ListenerSettings:
        return self.current


class FakeApiFactory:
    def __init__(self):
        self.api = ScriptedLookup()

    def __call__(self):
        return self.api


class RpcRecorder:
    def __init__(self):
        self.calls = []
        self.error = None

    def __call__(self, payload):
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return {"jsonrpc": "2.0", "result": "OK", "id": 1}


def enabled_settings(port: int = 0, bind: str = "127.0.0.1", token: str = TOKEN) -> ListenerSettings:
    return ListenerSettings(enabled=True, bind_host=bind, port=port, token=token)


def run_runtime(runtime: SendRuntime):
    thread = threading.Thread(target=runtime.run, name="send-runtime-test", daemon=True)
    thread.start()
    return thread


def wait_until(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_settings_defaults_are_disabled_loopback():
    addon = FakeAddon()
    settings = read_kodi_settings(addon)
    assert settings.enabled is False
    assert settings.bind_host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.token == ""
    assert not token_is_valid(settings.token)


def test_bind_and_port_validation():
    assert validate_bind_host("127.0.0.1") == "127.0.0.1"
    assert validate_bind_host("192.168.1.50") == "192.168.1.50"
    with pytest.raises(ValueError):
        validate_bind_host("0.0.0.0")
    with pytest.raises(ValueError):
        validate_bind_host("::1")
    with pytest.raises(ValueError):
        validate_bind_host("raspberrypi.local")
    assert validate_port(8765) == 8765
    assert validate_port(0, allow_ephemeral=True) == 0
    with pytest.raises(ValueError):
        validate_port(0)
    with pytest.raises(ValueError):
        validate_port(80)
    with pytest.raises(ValueError):
        validate_port(65536)


def test_kodi_adapter_play_and_browse_payloads():
    rpc = RpcRecorder()
    play = resolve_epika_url(VOD_URL, ScriptedLookup())
    dispatch_to_kodi(
        rpc,
        DispatchJob("abc", play.action, play.plugin_url, play.product_id, play.kind, play.title),
    )
    serial = resolve_epika_url(SERIAL_URL, ScriptedLookup())
    dispatch_to_kodi(
        rpc,
        DispatchJob("def", serial.action, serial.plugin_url, serial.product_id, serial.kind, serial.title),
    )
    season = resolve_epika_url(SEASON_URL, ScriptedLookup())
    dispatch_to_kodi(
        rpc,
        DispatchJob("ghi", season.action, season.plugin_url, season.product_id, season.kind, season.title),
    )
    assert rpc.calls[0]["method"] == "Player.Open"
    assert rpc.calls[0]["params"]["item"]["file"] == play.plugin_url
    assert rpc.calls[1]["method"] == "GUI.ActivateWindow"
    assert rpc.calls[1]["params"] == {"window": "videos", "parameters": [serial.plugin_url, "return"]}
    assert rpc.calls[2]["params"]["parameters"][0] == season.plugin_url
    assert rpc.calls[2]["params"]["parameters"][1] == "return"


def test_disabled_runtime_stays_dormant():
    monitor = FakeMonitor()
    logs = []
    runtime = SendRuntime(
        monitor,
        settings_reader=lambda: ListenerSettings(False, "127.0.0.1", 8765, TOKEN),
        api_factory=FakeApiFactory(),
        rpc=RpcRecorder(),
        logger=lambda level, **fields: logs.append((level, fields)),
        allow_ephemeral_port=True,
    )
    thread = run_runtime(runtime)
    assert wait_until(lambda: any(fields.get("event") == "listener_dormant" for _level, fields in logs))
    assert runtime.bound_address is None
    monitor.abort()
    thread.join(2)
    assert not thread.is_alive()
    assert runtime.bound_address is None


def test_settings_change_restarts_listener():
    monitor = FakeMonitor()
    settings = MutableSettings(ListenerSettings(False, "127.0.0.1", 0, TOKEN))
    runtime = SendRuntime(
        monitor,
        settings_reader=settings,
        api_factory=FakeApiFactory(),
        rpc=RpcRecorder(),
        logger=lambda level, **fields: None,
        allow_ephemeral_port=True,
    )
    thread = run_runtime(runtime)
    assert wait_until(lambda: runtime.bound_address is None)
    settings.current = enabled_settings()
    monitor.onSettingsChanged()
    assert wait_until(lambda: runtime.bound_address is not None)
    host, port = runtime.bound_address
    assert host == "127.0.0.1"
    assert port != 0
    settings.current = ListenerSettings(False, "127.0.0.1", 0, TOKEN)
    monitor.onSettingsChanged()
    assert wait_until(lambda: runtime.bound_address is None)
    monitor.abort()
    thread.join(2)
    assert not thread.is_alive()


def test_bind_collision_notifies_once_and_stays_alive():
    class OccupiedHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

    occupier = HTTPServer(("127.0.0.1", 0), OccupiedHandler)
    occupied_port = occupier.server_address[1]
    monitor = FakeMonitor()
    notifications = []
    runtime = SendRuntime(
        monitor,
        settings_reader=lambda: enabled_settings(port=occupied_port),
        api_factory=FakeApiFactory(),
        rpc=RpcRecorder(),
        logger=lambda level, **fields: None,
        notify=notifications.append,
        allow_ephemeral_port=True,
    )
    thread = run_runtime(runtime)
    assert wait_until(lambda: notifications == ["Send listener could not start."])
    assert runtime.bound_address is None
    occupier.server_close()
    monitor.abort()
    thread.join(2)
    assert not thread.is_alive()
    assert notifications == ["Send listener could not start."]


def test_shutdown_drains_and_releases_port():
    monitor = FakeMonitor()
    runtime = SendRuntime(
        monitor,
        settings_reader=lambda: enabled_settings(),
        api_factory=FakeApiFactory(),
        rpc=RpcRecorder(),
        logger=lambda level, **fields: None,
        allow_ephemeral_port=True,
    )
    thread = run_runtime(runtime)
    assert wait_until(lambda: runtime.bound_address is not None)
    host, port = runtime.bound_address
    monitor.abort()
    thread.join(2)
    assert not thread.is_alive()
    assert runtime.bound_address is None
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
    finally:
        probe.close()


def test_loopback_port0_integration_with_fakes():
    monitor = FakeMonitor()
    rpc = RpcRecorder()
    factory = FakeApiFactory()
    runtime = SendRuntime(
        monitor,
        settings_reader=lambda: enabled_settings(),
        api_factory=factory,
        rpc=rpc,
        logger=lambda level, **fields: None,
        allow_ephemeral_port=True,
        dispatch_wait=2.0,
    )
    thread = run_runtime(runtime)
    assert wait_until(lambda: runtime.bound_address is not None)
    host, port = runtime.bound_address
    body = json.dumps({"url": VOD_URL}).encode("utf-8")
    request = Request(
        f"http://{host}:{port}/v1/send",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=3) as response:
        payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 202
    assert payload["ok"] is True
    assert payload["action"] == "play"
    assert wait_until(lambda: len(rpc.calls) == 1)
    assert rpc.calls[0]["method"] == "Player.Open"
    file_url = rpc.calls[0]["params"]["item"]["file"]
    assert file_url.endswith("route=play&product_id=432486&item_type=VOD")
    assert factory.api.calls[0] == ("get_product", 432486)

    health = Request(
        f"http://{host}:{port}/v1/health",
        method="GET",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    with urlopen(health, timeout=3) as response:
        health_payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
    assert health_payload["service"] == "lrtepika-send"

    monitor.abort()
    thread.join(2)
    assert not thread.is_alive()
    with pytest.raises((URLError, ConnectionError, OSError)):
        urlopen(health, timeout=1)


def test_default_kodi_rpc_adapter_records_json():
    job = resolve_epika_url(VOD_URL, ScriptedLookup())
    dispatch_to_kodi(
        lambda payload: json.loads(__import__("xbmc").executeJSONRPC(json.dumps(payload))),
        DispatchJob("z", job.action, job.plugin_url, job.product_id, job.kind, job.title),
    )
    recorded = json.loads(KODI.jsonrpc_calls[0])
    assert recorded["method"] == "Player.Open"
    assert recorded["params"]["item"]["file"] == job.plugin_url
