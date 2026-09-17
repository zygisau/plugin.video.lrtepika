# MIT License
"""Send-to-Epika service lifecycle, settings, and Kodi JSON-RPC dispatch."""

from __future__ import annotations

import ipaddress
import json
import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib.api import EpikaApi
from resources.lib.send_http import (
    DISPATCH_WAIT_SECONDS,
    SERVICE_VERSION,
    Clock,
    Deduper,
    DispatchError,
    DispatchJob,
    RateLimiter,
    SendHttpApp,
    SendHTTPServer,
    create_server,
    default_resolver,
    token_digest,
    token_is_valid,
)
ADDON_ID = "plugin.video.lrtepika"
DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8765
API_TIMEOUT = (2.0, 4.0)
HTTP_JOIN_SECONDS = 2.0
QUEUE_SIZE = 1
QUEUE_PUT_SECONDS = 0.1
NOTIFY_MESSAGE = "Send listener could not start."


@dataclass(frozen=True)
class ListenerSettings:
    enabled: bool
    bind_host: str
    port: int
    token: str


class QueueDispatcher:
    def __init__(
        self,
        jobs: queue.Queue,
        accepting: Callable[[], bool],
        wait_seconds: float = DISPATCH_WAIT_SECONDS,
    ):
        self._jobs = jobs
        self._accepting = accepting
        self._wait_seconds = wait_seconds

    def __call__(self, job: DispatchJob) -> None:
        if not self._accepting():
            raise DispatchError("stopping")
        done = threading.Event()
        envelope = {"job": job, "event": done, "error": None}
        try:
            self._jobs.put(envelope, timeout=QUEUE_PUT_SECONDS)
        except queue.Full as exc:
            raise DispatchError("queue_full") from exc
        if not done.wait(self._wait_seconds):
            raise DispatchError("timeout")
        error = envelope.get("error")
        if error:
            raise DispatchError(str(error))


class SendMonitor(xbmc.Monitor):
    def __init__(self):
        super().__init__()
        self.owner = None

    def onSettingsChanged(self):
        owner = self.owner
        if owner is not None:
            owner.notify_settings_changed()


class SendRuntime:
    def __init__(
        self,
        monitor,
        settings_reader: Callable[[], ListenerSettings] | None = None,
        rpc: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        api_factory: Callable[[], Any] | None = None,
        clock: Clock | None = None,
        logger: Callable[..., None] | None = None,
        notify: Callable[[str], None] | None = None,
        dispatch_wait: float = DISPATCH_WAIT_SECONDS,
        allow_ephemeral_port: bool = False,
    ):
        self.monitor = monitor
        self.settings_reader = settings_reader or read_kodi_settings
        self.rpc = rpc or execute_kodi_rpc
        self.api_factory = api_factory or (lambda: EpikaApi(timeout=API_TIMEOUT))
        self.clock = clock or Clock()
        self.logger = logger or kodi_log
        self.notify = notify or notify_error
        self.dispatch_wait = dispatch_wait
        self.allow_ephemeral_port = allow_ephemeral_port
        self._settings_changed = threading.Event()
        self._accepting = threading.Event()
        self._jobs: queue.Queue = queue.Queue(maxsize=QUEUE_SIZE)
        self._httpd: SendHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._api = None
        self._bind_notified = False
        if hasattr(self.monitor, "owner"):
            self.monitor.owner = self

    @property
    def bound_address(self) -> tuple[str, int] | None:
        if self._httpd is None:
            return None
        return self._httpd.server_address[:2]

    def notify_settings_changed(self) -> None:
        self._settings_changed.set()

    def run(self) -> None:
        try:
            self.apply_settings()
            while not self._aborting():
                if self._settings_changed.is_set():
                    self._settings_changed.clear()
                    self.apply_settings()
                self.pump_dispatch(0.05)
                if self.monitor.waitForAbort(0.2):
                    break
        finally:
            self.shutdown()

    def apply_settings(self) -> None:
        self._stop_listener()
        try:
            settings = self.settings_reader()
        except Exception:
            self.logger("error", error="settings_read_failed")
            self._notify_bind_failure()
            return
        if not settings.enabled:
            self.logger("info", event="listener_dormant")
            return
        try:
            host = validate_bind_host(settings.bind_host)
            port = validate_port(settings.port, allow_ephemeral=self.allow_ephemeral_port)
            if not token_is_valid(settings.token):
                raise ValueError("invalid token")
        except ValueError:
            self.logger("error", error="invalid_settings")
            self._notify_bind_failure()
            return
        try:
            self._start_listener(host, port, settings.token)
        except OSError:
            self.logger("error", error="bind_failed", bind=host, port=port)
            self._notify_bind_failure()
            return
        self._bind_notified = False
        self.logger("info", event="listener_start", bind=host, port=self.bound_address[1] if self.bound_address else port)

    def pump_dispatch(self, timeout: float) -> None:
        try:
            envelope = self._jobs.get(timeout=timeout)
        except queue.Empty:
            return
        try:
            if self._aborting() or not self._accepting.is_set():
                envelope["error"] = "stopping"
            else:
                job = envelope["job"]
                try:
                    dispatch_to_kodi(self.rpc, job)
                except Exception:
                    envelope["error"] = "failed"
                    self.logger(
                        "error",
                        error="dispatch_failed",
                        request_id=job.request_id,
                        action=job.action,
                        product_id=job.product_id,
                        kind=job.kind,
                    )
        finally:
            envelope["event"].set()

    def shutdown(self) -> None:
        self._accepting.clear()
        self._stop_listener()
        self._drain_jobs("stopping")

    def _start_listener(self, host: str, port: int, token: str) -> None:
        self._api = self.api_factory()
        limiter = RateLimiter(self.clock)
        deduper = Deduper(self.clock)
        dispatcher = QueueDispatcher(self._jobs, self._accepting.is_set, self.dispatch_wait)
        app = SendHttpApp(
            token_digest=token_digest(token),
            resolver=default_resolver(self._api),
            dispatcher=dispatcher,
            limiter=limiter,
            deduper=deduper,
            clock=self.clock,
            log=self.logger,
            is_accepting=self._accepting.is_set,
            version=_addon_version(),
            dispatch_timeout=self.dispatch_wait,
        )
        httpd = create_server(host, port, app)
        started = threading.Event()

        def _serve():
            started.set()
            try:
                httpd.serve_forever(poll_interval=0.2)
            except Exception:
                self.logger("error", error="listener_crash")

        thread = threading.Thread(target=_serve, name="lrtepika-send", daemon=True)
        self._httpd = httpd
        self._thread = thread
        self._accepting.set()
        thread.start()
        if not started.wait(1.0):
            self._accepting.clear()
            raise OSError("listener thread failed")

    def _stop_listener(self) -> None:
        self._accepting.clear()
        httpd = self._httpd
        thread = self._thread
        self._httpd = None
        self._thread = None
        self._api = None
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:
                pass
            try:
                httpd.server_close()
            except Exception:
                pass
        if thread is not None and thread.is_alive():
            thread.join(HTTP_JOIN_SECONDS)
            if thread.is_alive():
                self.logger("warning", error="listener_join_timeout")
        self._drain_jobs("stopping")

    def _drain_jobs(self, reason: str) -> None:
        while True:
            try:
                envelope = self._jobs.get_nowait()
            except queue.Empty:
                return
            envelope["error"] = reason
            event = envelope.get("event")
            if event is not None:
                event.set()

    def _aborting(self) -> bool:
        try:
            return bool(self.monitor.abortRequested())
        except Exception:
            return True

    def _notify_bind_failure(self) -> None:
        if self._bind_notified:
            return
        self._bind_notified = True
        try:
            self.notify(NOTIFY_MESSAGE)
        except Exception:
            return


def run(**kwargs: Any) -> None:
    monitor = kwargs.pop("monitor", None) or SendMonitor()
    SendRuntime(monitor, **kwargs).run()


def read_kodi_settings(addon=None) -> ListenerSettings:
    addon = addon or xbmcaddon.Addon()
    enabled = _setting_bool(addon, "send_enabled", False)
    bind_host = _setting_text(addon, "send_bind", DEFAULT_BIND) or DEFAULT_BIND
    port = _setting_int(addon, "send_port", DEFAULT_PORT)
    token = _setting_text(addon, "send_token", "")
    return ListenerSettings(enabled=enabled, bind_host=bind_host, port=port, token=token)


def validate_bind_host(host: str) -> str:
    text = (host or "").strip()
    try:
        ip = ipaddress.IPv4Address(text)
    except (ipaddress.AddressValueError, ValueError) as exc:
        raise ValueError("invalid bind address") from exc
    if ip.is_unspecified or ip.is_multicast:
        raise ValueError("invalid bind address")
    return str(ip)


def validate_port(port: Any, allow_ephemeral: bool = False) -> int:
    if isinstance(port, bool) or not isinstance(port, int):
        raise ValueError("invalid port")
    if allow_ephemeral and port == 0:
        return 0
    if port < 1024 or port > 65535:
        raise ValueError("invalid port")
    return port


def execute_kodi_rpc(payload: dict[str, Any]) -> dict[str, Any]:
    raw = xbmc.executeJSONRPC(json.dumps(payload, separators=(",", ":")))
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise DispatchError("failed") from exc
    if not isinstance(data, dict) or "error" in data:
        raise DispatchError("failed")
    return data


def dispatch_to_kodi(rpc: Callable[[dict[str, Any]], dict[str, Any]], job: DispatchJob) -> None:
    if job.action == "play":
        payload = {
            "jsonrpc": "2.0",
            "method": "Player.Open",
            "params": {"item": {"file": job.plugin_url}},
            "id": 1,
        }
    elif job.action == "browse":
        payload = {
            "jsonrpc": "2.0",
            "method": "GUI.ActivateWindow",
            "params": {"window": "videos", "parameters": [job.plugin_url, "return"]},
            "id": 1,
        }
    else:
        raise DispatchError("failed")
    rpc(payload)


def kodi_log(level: str, **fields: Any) -> None:
    xbmc_level = {
        "debug": xbmc.LOGDEBUG,
        "info": xbmc.LOGINFO,
        "warning": xbmc.LOGWARNING,
        "error": xbmc.LOGERROR,
    }.get(level, xbmc.LOGINFO)
    parts = [f"{key}={fields[key]}" for key in sorted(fields) if fields[key] is not None]
    xbmc.log(f"{ADDON_ID}: send " + " ".join(parts), xbmc_level)


def notify_error(message: str) -> None:
    xbmcgui.Dialog().notification("LRT Epika", message, xbmcgui.NOTIFICATION_ERROR)


def _addon_version() -> str:
    try:
        version = xbmcaddon.Addon().getAddonInfo("version")
    except Exception:
        version = ""
    return version or SERVICE_VERSION


def _setting_text(addon, key: str, default: str) -> str:
    try:
        value = addon.getSetting(key)
    except Exception:
        return default
    if value is None:
        return default
    return str(value)


def _setting_bool(addon, key: str, default: bool) -> bool:
    if hasattr(addon, "getSettingBool"):
        try:
            return bool(addon.getSettingBool(key))
        except Exception:
            pass
    raw = _setting_text(addon, key, "")
    if raw.lower() in ("true", "1"):
        return True
    if raw.lower() in ("false", "0", ""):
        return False
    return default


def _setting_int(addon, key: str, default: int) -> int:
    if hasattr(addon, "getSettingInt"):
        try:
            return int(addon.getSettingInt(key))
        except Exception:
            pass
    raw = _setting_text(addon, key, str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
