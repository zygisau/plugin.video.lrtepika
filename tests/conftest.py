# MIT License
"""Pytest fixtures and fake Kodi modules (no Kodistubs)."""

from __future__ import annotations

import sys
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
    def __init__(self, default="", heading="", hidden=False):
        self.default = default
        self.heading = heading
        self.hidden = hidden
        self._text = default
        self._confirmed = False

    def doModal(self):
        return None

    def isConfirmed(self):
        return self._confirmed

    def getText(self):
        return self._text


class FakeAddon:
    def __init__(self, id=None):
        self._id = id or "plugin.video.lrtepika"
        self._settings = {}

    def getAddonInfo(self, key):
        mapping = {
            "id": self._id,
            "name": "LRT Epika",
            "version": "0.1.0",
            "path": str(ROOT),
            "profile": str(ROOT / "tests" / "_profile"),
            "author": "zygisau",
        }
        return mapping.get(key, "")

    def getSetting(self, key):
        return self._settings.get(key, "")

    def setSetting(self, key, value):
        self._settings[key] = value


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

    def log(message, level=xbmc.LOGINFO):
        state.logs.append((level, str(message)))

    xbmc.log = log

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
    KODI.plugin_category = None
    KODI.content = None
