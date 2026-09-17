# MIT License
"""Pytest fixtures and fake Kodi modules (no Kodistubs)."""

from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeInfoTag:
    def __init__(self):
        self.media_type = None
        self.title = None
        self.plot = None
        self.year = None
        self.duration = None
        self.genres = []
        self.season = None
        self.episode = None

    def setMediaType(self, value):
        self.media_type = value

    def setTitle(self, value):
        self.title = value

    def setPlot(self, value):
        self.plot = value

    def setYear(self, value):
        self.year = value

    def setDuration(self, value):
        self.duration = value

    def setGenres(self, value):
        self.genres = list(value or [])

    def setSeason(self, value):
        self.season = value

    def setEpisode(self, value):
        self.episode = value


class FakeListItem:
    def __init__(self, label="", path="", offscreen=False):
        self.label = label
        self.path = path
        self.offscreen = offscreen
        self.art = {}
        self.properties = {}
        self.subtitles = []
        self.mime_type = None
        self.content_lookup = None
        self._info_tag = FakeInfoTag()

    def setLabel(self, label):
        self.label = label

    def setPath(self, path):
        self.path = path

    def setArt(self, art):
        self.art.update(art or {})

    def setProperty(self, key, value):
        self.properties[key] = value

    def setSubtitles(self, urls):
        self.subtitles = list(urls or [])

    def setMimeType(self, mime_type):
        self.mime_type = mime_type

    def setContentLookup(self, enabled):
        self.content_lookup = enabled

    def getVideoInfoTag(self):
        return self._info_tag


class FakeDialog:
    notifications = []

    def notification(self, heading, message, icon=None, time=None, sound=None):
        self.notifications.append(
            {
                "heading": heading,
                "message": message,
                "icon": icon,
                "time": time,
                "sound": sound,
            }
        )


class FakeKeyboard:
    instances = []
    next_text = ""
    next_confirmed = False

    def __init__(self, default="", heading="", hidden=False):
        self.default = default
        self.heading = heading
        self.hidden = hidden
        self._text = FakeKeyboard.next_text
        self._confirmed = FakeKeyboard.next_confirmed
        FakeKeyboard.instances.append(self)

    def doModal(self):
        return None

    def isConfirmed(self):
        return self._confirmed

    def getText(self):
        return self._text


class FakeAddon:
    def __init__(self, id=None):
        self._id = id or "plugin.video.lrtepika"
        self._settings = {
            "send_enabled": "false",
            "send_bind": "127.0.0.1",
            "send_port": "8765",
            "send_token": "",
        }

    def getAddonInfo(self, key):
        mapping = {
            "id": self._id,
            "name": "LRT Epika",
            "version": "0.2.0",
            "path": str(ROOT),
            "profile": str(ROOT / "tests" / "_profile"),
            "author": "zygisau",
        }
        return mapping.get(key, "")

    def getSetting(self, key):
        return str(self._settings.get(key, ""))

    def getSettingBool(self, key):
        value = self._settings.get(key, False)
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1")

    def getSettingInt(self, key):
        value = self._settings.get(key, 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def setSetting(self, key, value):
        self._settings[key] = value


class FakeMonitor:
    def __init__(self):
        self._abort = threading.Event()
        self.owner = None

    def abortRequested(self):
        return self._abort.is_set()

    def waitForAbort(self, timeout=0):
        return self._abort.wait(timeout or 0)

    def onSettingsChanged(self):
        if self.owner is not None:
            self.owner.notify_settings_changed()

    def abort(self):
        self._abort.set()


class PluginState:
    def __init__(self):
        self.directory_items = []
        self.end_of_directory_calls = []
        self.resolved = []
        self.plugin_category = None
        self.content = None
        self.sort_methods = []
        self.logs = []
        self.notifications = FakeDialog.notifications
        self.keyboard_instances = FakeKeyboard.instances
        self.jsonrpc_calls = []
        self.jsonrpc_result = '{"jsonrpc":"2.0","result":"OK","id":1}'


def _install_fakes():
    state = PluginState()
    FakeDialog.notifications = state.notifications

    xbmc = types.ModuleType("xbmc")
    xbmc.LOGDEBUG = 0
    xbmc.LOGINFO = 1
    xbmc.LOGWARNING = 2
    xbmc.LOGERROR = 3
    xbmc.LOGFATAL = 4
    xbmc.Keyboard = FakeKeyboard
    xbmc.Monitor = FakeMonitor

    def log(message, level=xbmc.LOGINFO):
        state.logs.append((level, str(message)))

    xbmc.log = log

    def executeJSONRPC(payload):
        state.jsonrpc_calls.append(payload)
        return state.jsonrpc_result

    xbmc.executeJSONRPC = executeJSONRPC

    xbmcgui = types.ModuleType("xbmcgui")
    xbmcgui.ListItem = FakeListItem
    xbmcgui.Dialog = FakeDialog
    xbmcgui.NOTIFICATION_INFO = "info"
    xbmcgui.NOTIFICATION_ERROR = "error"
    xbmcgui.NOTIFICATION_WARNING = "warning"

    xbmcplugin = types.ModuleType("xbmcplugin")
    xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE = 1
    xbmcplugin.SORT_METHOD_VIDEO_YEAR = 2
    xbmcplugin.SORT_METHOD_NONE = 0
    xbmcplugin.SORT_METHOD_UNSORTED = 3

    def addDirectoryItem(handle, url, listitem, isFolder=False, totalItems=0):
        state.directory_items.append(
            {
                "handle": handle,
                "url": url,
                "listitem": listitem,
                "is_folder": isFolder,
                "total_items": totalItems,
            }
        )
        return True

    def addDirectoryItems(handle, items, totalItems=0):
        ok = True
        for item in items:
            url, listitem, is_folder = item
            ok = addDirectoryItem(handle, url, listitem, is_folder, totalItems) and ok
        return ok

    def endOfDirectory(handle, succeeded=True, updateListing=False, cacheToDisc=True):
        state.end_of_directory_calls.append(
            {
                "handle": handle,
                "succeeded": succeeded,
                "update_listing": updateListing,
                "cache_to_disc": cacheToDisc,
            }
        )

    def setResolvedUrl(handle, succeeded, listitem):
        state.resolved.append(
            {"handle": handle, "succeeded": succeeded, "listitem": listitem}
        )

    def setPluginCategory(handle, category):
        state.plugin_category = category

    def setContent(handle, content):
        state.content = content

    def addSortMethod(handle, sortMethod):
        state.sort_methods.append(sortMethod)

    xbmcplugin.addDirectoryItem = addDirectoryItem
    xbmcplugin.addDirectoryItems = addDirectoryItems
    xbmcplugin.endOfDirectory = endOfDirectory
    xbmcplugin.setResolvedUrl = setResolvedUrl
    xbmcplugin.setPluginCategory = setPluginCategory
    xbmcplugin.setContent = setContent
    xbmcplugin.addSortMethod = addSortMethod

    xbmcaddon = types.ModuleType("xbmcaddon")
    xbmcaddon.Addon = FakeAddon

    xbmcvfs = types.ModuleType("xbmcvfs")

    def translatePath(path):
        return str(path)

    xbmcvfs.translatePath = translatePath

    sys.modules["xbmc"] = xbmc
    sys.modules["xbmcgui"] = xbmcgui
    sys.modules["xbmcplugin"] = xbmcplugin
    sys.modules["xbmcaddon"] = xbmcaddon
    sys.modules["xbmcvfs"] = xbmcvfs
    return state


KODI = _install_fakes()


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "live: read-only live LRT Epika API checks"
    )


def pytest_runtest_setup(item):
    KODI.directory_items.clear()
    KODI.end_of_directory_calls.clear()
    KODI.resolved.clear()
    KODI.logs.clear()
    KODI.notifications.clear()
    KODI.sort_methods.clear()
    KODI.jsonrpc_calls.clear()
    KODI.jsonrpc_result = '{"jsonrpc":"2.0","result":"OK","id":1}'
    FakeKeyboard.instances.clear()
    FakeKeyboard.next_text = ""
    FakeKeyboard.next_confirmed = False
    KODI.plugin_category = None
    KODI.content = None
