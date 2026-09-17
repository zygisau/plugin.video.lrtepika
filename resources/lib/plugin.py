# MIT License
"""Kodi routes for LRT Epika navigation and playback."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib.api import ApiError, EpikaApi
from resources.lib.routes import DEFAULT_BASE_URL, build_plugin_url
from resources.lib.directory import (
    FEATURED_SECTION,
    MOVIE_MAIN_CATEGORIES,
    MOVIE_MAIN_CATEGORY_IDS,
    MOVIES_FEATURED_SECTION,
    PAGE_SIZE,
    SERIES_FEATURED_SECTION,
    SERIES_MAIN_CATEGORIES,
    SERIES_MAIN_CATEGORY_IDS,
    DirectoryItem,
    coerce_int,
    find_section,
    parse_catalog_page,
    parse_item_list,
    parse_playlist,
    parse_search_page,
    parse_sections,
)
from resources.lib.history import HISTORY_FILENAME, HISTORY_LIMIT, add_history, load_history, normalize_term

ADDON_ID = "plugin.video.lrtepika"
NEXT_PAGE_LABEL = "Next page"
EMPTY_MESSAGE = "No titles in this folder."
LOAD_ERROR_MESSAGE = "Unable to load this folder."
PLAY_ERROR_MESSAGE = "Unable to play this title."
SEARCH_EMPTY_MESSAGE = "No search results."
NEW_SEARCH_LABEL = "New search…"
SEARCH_LOOKAHEAD = PAGE_SIZE + 1
SEARCH_OFFSET_PARAMS = (
    ("VOD", "vod_offset"),
    ("SERIAL", "serial_offset"),
    ("EPISODE", "episode_offset"),
)
LICENSE_HEADERS = "Content-Type=application/octet-stream"
PLAYLIST_TYPE = {"VOD": "MOVIE", "EPISODE": "EPISODE"}
DASH_MIME = "application/dash+xml"
HLS_MIME = "application/vnd.apple.mpegurl"


def run(argv, api=None, history_path=None):
    """Start the plugin with Kodi's `sys.argv` vector."""
    Plugin(argv, api=api, history_path=history_path).dispatch()


def _resolve_history_path(history_path: str | Path | None) -> Path | None:
    if history_path is not None:
        text = str(history_path).strip()
        return Path(text) if text else None
    try:
        profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo("profile") or "")
    except Exception:
        profile = ""
    if not isinstance(profile, str) or not profile.strip():
        return None
    return Path(profile) / HISTORY_FILENAME


def _log(message: str, level: int = xbmc.LOGERROR) -> None:
    xbmc.log(f"{ADDON_ID}: {message}", level)


def _addon_name() -> str:
    try:
        return xbmcaddon.Addon().getAddonInfo("name") or "LRT Epika"
    except Exception:
        return "LRT Epika"


def _notify(message: str, error: bool = False) -> None:
    icon = xbmcgui.NOTIFICATION_ERROR if error else xbmcgui.NOTIFICATION_INFO
    xbmcgui.Dialog().notification(_addon_name(), message, icon)


def _parse_categories(payload: Any) -> list[tuple[int, str]]:
    if not isinstance(payload, list):
        return []
    categories: list[tuple[int, str]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        category_id = coerce_int(raw.get("id"))
        name = raw.get("name")
        if category_id is None or not isinstance(name, str):
            continue
        label = name.strip()
        if not label:
            continue
        categories.append((category_id, label))
    return categories


class Plugin:
    def __init__(self, argv: list[str], api: EpikaApi | None = None, history_path=None):
        self.base_url = argv[0] if argv else DEFAULT_BASE_URL
        try:
            self.handle = int(argv[1]) if len(argv) > 1 else -1
        except (TypeError, ValueError):
            self.handle = -1
        raw = argv[2] if len(argv) > 2 else ""
        if raw.startswith("?"):
            raw = raw[1:]
        self.params = dict(parse_qsl(raw, keep_blank_values=True))
        self.api = api or EpikaApi()
        self.history_path = _resolve_history_path(history_path)

    def dispatch(self) -> None:
        route = self.params.get("route") or None
        if route == "play":
            self._dispatch_play()
            return
        self._dispatch_directory(route)

    def url(self, **kwargs: Any) -> str:
        return build_plugin_url(self.base_url, **kwargs)

    def _dispatch_directory(self, route: str | None) -> None:
        handlers = {
            None: self.list_root,
            "featured": self.list_featured,
            "section": self.list_section,
            "movies": self.list_movies_hub,
            "series": self.list_series_hub,
            "genres": self.list_genres,
            "catalog": self.list_catalog,
            "serial": self.list_seasons,
            "episodes": self.list_episodes,
            "search": self.list_search,
            "search_new": self.list_search_new,
            "search_results": self.list_search_results,
        }
        handler = handlers.get(route)
        try:
            if handler is None:
                raise ApiError("dispatch", "unknown route")
            handler()
            xbmcplugin.endOfDirectory(self.handle, succeeded=True, cacheToDisc=False)
        except ApiError as exc:
            _log(str(exc))
            _notify(LOAD_ERROR_MESSAGE, error=True)
            xbmcplugin.endOfDirectory(self.handle, succeeded=False, cacheToDisc=False)

    def _dispatch_play(self) -> None:
        try:
            self.play()
        except ApiError as exc:
            self._fail_play(str(exc))
        except Exception:
            self._fail_play(PLAY_ERROR_MESSAGE)

    def _fail_play(self, reason: str) -> None:
        _log(reason)
        _notify(PLAY_ERROR_MESSAGE, error=True)
        xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())

    def _set_heading(self, category: str, content: str) -> None:
        xbmcplugin.setPluginCategory(self.handle, category)
        xbmcplugin.setContent(self.handle, content)

    def _add_items(self, entries: list[tuple[str, xbmcgui.ListItem, bool]]) -> None:
        xbmcplugin.addDirectoryItems(self.handle, entries, len(entries))

    def _folder(self, label: str, url: str, special_sort: str | None = None) -> tuple[str, xbmcgui.ListItem, bool]:
        listitem = xbmcgui.ListItem(label=label, offscreen=True)
        listitem.setPath(url)
        info = listitem.getVideoInfoTag()
        info.setTitle(label)
        info.setMediaType("video")
        if special_sort:
            listitem.setProperty("SpecialSort", special_sort)
        return url, listitem, True

    def _listitem(self, item: DirectoryItem) -> xbmcgui.ListItem:
        listitem = xbmcgui.ListItem(label=item.title or str(item.id), offscreen=True)
        info = listitem.getVideoInfoTag()
        info.setMediaType(item.media_type)
        if item.title:
            info.setTitle(item.title)
        if item.plot:
            info.setPlot(item.plot)
        if item.year is not None:
            info.setYear(item.year)
        if item.duration is not None:
            info.setDuration(item.duration)
        if item.genres:
            info.setGenres(list(item.genres))
        if item.season_number is not None:
            info.setSeason(item.season_number)
        if item.episode_number is not None:
            info.setEpisode(item.episode_number)
        art = {key: value for key, value in item.art.items() if value}
        if art:
            listitem.setArt(art)
        if item.is_playable:
            listitem.setProperty("IsPlayable", "true")
        return listitem

    def _item_url(self, item: DirectoryItem, extra: dict[str, Any] | None = None) -> str:
        extra = extra or {}
        if item.type == "VOD":
            return self.url(route="play", product_id=item.id, item_type="VOD")
        if item.type == "SERIAL":
            return self.url(route="serial", serial_id=item.id, title=item.title or None)
        if item.type == "SEASON":
            return self.url(
                route="episodes",
                serial_id=extra.get("serial_id"),
                season_id=item.id,
                title=item.title or None,
            )
        if item.type == "EPISODE":
            return self.url(route="play", product_id=item.id, item_type="EPISODE")
        return self.base_url

    def _entry(self, item: DirectoryItem, extra: dict[str, Any] | None = None) -> tuple[str, xbmcgui.ListItem, bool]:
        url = self._item_url(item, extra)
        listitem = self._listitem(item)
        listitem.setPath(url)
        return url, listitem, item.is_folder

    def _main_ids(self) -> list[int]:
        raw = self.params.get("main_ids", "")
        ids: list[int] = []
        for part in raw.split(","):
            value = coerce_int(part)
            if value is not None:
                ids.append(value)
        return ids

    def _catalog_content(self, main_ids: Iterable[int]) -> str:
        ids = set(main_ids)
        if ids and ids.issubset(set(MOVIE_MAIN_CATEGORY_IDS)):
            return "movies"
        if ids and ids.issubset(set(SERIES_MAIN_CATEGORY_IDS)):
            return "tvshows"
        return "videos"

    def _empty(self, message: str = EMPTY_MESSAGE) -> None:
        _notify(message, error=False)

    def list_root(self) -> None:
        self._set_heading("LRT Epika", "files")
        self._add_items(
            [
                self._folder("Featured", self.url(route="featured", section_name=FEATURED_SECTION)),
                self._folder("Movies", self.url(route="movies")),
                self._folder("Series", self.url(route="series")),
                self._folder("Search", self.url(route="search")),
            ]
        )

    def list_featured(self) -> None:
        section_name = self.params.get("section_name") or FEATURED_SECTION
        title = self.params.get("title") or "Featured"
        self._set_heading(title, "files")
        sections = parse_sections(self.api.get_sections(section_name))
        if not sections:
            self._empty()
            return
        entries = [
            self._folder(
                section.title or str(section.id),
                self.url(
                    route="section",
                    section_name=section_name,
                    section_id=section.id,
                    title=section.title or None,
                ),
            )
            for section in sections
        ]
        self._add_items(entries)

    def list_section(self) -> None:
        section_name = self.params.get("section_name") or FEATURED_SECTION
        title = self.params.get("title") or "Featured"
        self._set_heading(title, "videos")
        sections = parse_sections(self.api.get_sections(section_name))
        section = find_section(sections, self.params.get("section_id"))
        if section is None or not section.items:
            self._empty()
            return
        self._add_items([self._entry(item) for item in section.items])

    def list_movies_hub(self) -> None:
        self._set_heading("Movies", "files")
        all_ids = ",".join(str(item) for item in MOVIE_MAIN_CATEGORY_IDS)
        entries = [
            self._folder(
                "Featured",
                self.url(route="featured", section_name=MOVIES_FEATURED_SECTION, title="Featured"),
            ),
            self._folder("All", self.url(route="catalog", main_ids=all_ids, title="All")),
        ]
        for category_id, label in MOVIE_MAIN_CATEGORIES:
            entries.append(
                self._folder(label, self.url(route="genres", main_id=category_id, title=label))
            )
        self._add_items(entries)

    def list_series_hub(self) -> None:
        self._set_heading("Series", "files")
        all_ids = ",".join(str(item) for item in SERIES_MAIN_CATEGORY_IDS)
        entries = [
            self._folder(
                "Featured",
                self.url(route="featured", section_name=SERIES_FEATURED_SECTION, title="Featured"),
            ),
            self._folder("All", self.url(route="catalog", main_ids=all_ids, title="All")),
        ]
        for category_id, label in SERIES_MAIN_CATEGORIES:
            entries.append(
                self._folder(label, self.url(route="genres", main_id=category_id, title=label))
            )
        self._add_items(entries)

    def list_genres(self) -> None:
        main_id = coerce_int(self.params.get("main_id"))
        if main_id is None:
            raise ApiError("dispatch", "invalid main_id")
        title = self.params.get("title") or "Category"
        self._set_heading(title, "files")
        genres = _parse_categories(self.api.get_categories(main_id))
        entries = [
            self._folder("All", self.url(route="catalog", main_ids=str(main_id), title="All")),
        ]
        for genre_id, name in genres:
            entries.append(
                self._folder(
                    name,
                    self.url(
                        route="catalog",
                        main_ids=str(main_id),
                        category_id=genre_id,
                        title=name,
                    ),
                )
            )
        self._add_items(entries)

    def list_catalog(self) -> None:
        main_ids = self._main_ids()
        if not main_ids:
            raise ApiError("dispatch", "invalid main_ids")
        category_id = coerce_int(self.params.get("category_id"))
        first_result = coerce_int(self.params.get("first_result")) or 0
        title = self.params.get("title") or "Catalog"
        self._set_heading(title, self._catalog_content(main_ids))
        category_ids = [category_id] if category_id is not None else None
        page = parse_catalog_page(
            self.api.get_catalog(
                main_ids,
                category_ids,
                first_result=first_result,
                max_results=PAGE_SIZE,
            ),
            first_result=first_result,
            page_size=PAGE_SIZE,
        )
        if not page.items:
            self._empty()
            return
        entries = [self._entry(item) for item in page.items]
        if page.has_next:
            next_params: dict[str, Any] = {
                "route": "catalog",
                "main_ids": ",".join(str(item) for item in main_ids),
                "first_result": page.first_result + page.page_size,
                "title": title,
            }
            if category_id is not None:
                next_params["category_id"] = category_id
            entries.append(self._folder(NEXT_PAGE_LABEL, self.url(**next_params), special_sort="bottom"))
        self._add_items(entries)

    def list_seasons(self) -> None:
        serial_id = coerce_int(self.params.get("serial_id"))
        if serial_id is None:
            raise ApiError("dispatch", "invalid serial_id")
        title = self.params.get("title") or "Series"
        self._set_heading(title, "seasons")
        items = parse_item_list(self.api.get_serial_seasons(serial_id))
        if not items:
            self._empty()
            return
        self._add_items([self._entry(item, {"serial_id": serial_id}) for item in items])

    def list_episodes(self) -> None:
        serial_id = coerce_int(self.params.get("serial_id"))
        season_id = coerce_int(self.params.get("season_id"))
        if serial_id is None or season_id is None:
            raise ApiError("dispatch", "invalid season")
        title = self.params.get("title") or "Episodes"
        self._set_heading(title, "episodes")
        items = parse_item_list(self.api.get_season_episodes(serial_id, season_id))
        if not items:
            self._empty()
            return
        self._add_items([self._entry(item) for item in items])

    def list_search(self) -> None:
        self._set_heading("Search", "files")
        entries = [self._folder(NEW_SEARCH_LABEL, self.url(route="search_new"))]
        for term in self._history_terms():
            entries.append(self._folder(term, self.url(route="search_results", keyword=term)))
        self._add_items(entries)

    def list_search_new(self) -> None:
        keyboard = xbmc.Keyboard("", "Search", False)
        keyboard.doModal()
        if not keyboard.isConfirmed():
            self.list_search()
            return
        term = normalize_term(keyboard.getText())
        if not term:
            self.list_search()
            return
        self._remember_term(term)
        self.params["keyword"] = term
        for _item_type, param_name in SEARCH_OFFSET_PARAMS:
            self.params.pop(param_name, None)
        self.list_search_results()

    def list_search_results(self) -> None:
        keyword = normalize_term(self.params.get("keyword"))
        if not keyword:
            self.list_search()
            return
        self._set_heading(keyword, "videos")
        pages, failures = self._search_pages(keyword)
        if failures:
            raise failures[0]
        items: list[DirectoryItem] = []
        seen: set[tuple[str, int]] = set()
        next_offsets: dict[str, int] = {}
        has_next = False
        for item_type, param_name, offset, page in pages:
            if page is None or offset < 0:
                next_offsets[param_name] = -1
                continue
            for item in page.items:
                key = (item.type, item.id)
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)
            if page.has_next:
                next_offsets[param_name] = offset + PAGE_SIZE
                has_next = True
            else:
                next_offsets[param_name] = -1
        if not items:
            self._empty(SEARCH_EMPTY_MESSAGE)
            return
        entries = [self._entry(item) for item in items]
        if has_next:
            entries.append(
                self._folder(
                    NEXT_PAGE_LABEL,
                    self.url(route="search_results", keyword=keyword, **next_offsets),
                    special_sort="bottom",
                )
            )
        self._add_items(entries)

    def _history_terms(self) -> list[str]:
        if self.history_path is None:
            return []
        try:
            return load_history(self.history_path, limit=HISTORY_LIMIT)
        except Exception:
            return []

    def _remember_term(self, term: str) -> None:
        if self.history_path is None:
            _log("unable to save search history", xbmc.LOGWARNING)
            return
        try:
            add_history(self.history_path, term, limit=HISTORY_LIMIT)
        except Exception:
            _log("unable to save search history", xbmc.LOGWARNING)

    def _search_offset(self, name: str) -> int:
        value = coerce_int(self.params.get(name))
        if value is None:
            return 0
        if value < 0:
            return -1
        return value

    def _search_pages(self, keyword: str):
        pages = []
        failures: list[ApiError] = []
        for item_type, param_name in SEARCH_OFFSET_PARAMS:
            offset = self._search_offset(param_name)
            if offset < 0:
                pages.append((item_type, param_name, offset, None))
                continue
            try:
                payload = self.api.search(
                    item_type,
                    keyword,
                    first_result=offset,
                    max_results=SEARCH_LOOKAHEAD,
                )
                page = parse_search_page(payload, first_result=offset, page_size=PAGE_SIZE)
                pages.append((item_type, param_name, offset, page))
            except ApiError as exc:
                failures.append(exc)
                pages.append((item_type, param_name, offset, None))
        return pages, failures

    def play(self) -> None:
        product_id = coerce_int(self.params.get("product_id"))
        item_type = self.params.get("item_type")
        video_type = PLAYLIST_TYPE.get(item_type or "")
        if product_id is None or video_type is None:
            self._fail_play("unsupported item type")
            return
        playlist = parse_playlist(self._load_playlist(product_id, video_type))
        if playlist is None:
            self._fail_play("no playlist")
            return
        stream_url, manifest_type, mime_type = _select_stream(playlist)
        if not stream_url:
            self._fail_play("no stream")
            return
        listitem = xbmcgui.ListItem(path=stream_url, offscreen=True)
        listitem.setProperty("inputstream", "inputstream.adaptive")
        listitem.setProperty("inputstream.adaptive.manifest_type", manifest_type)
        listitem.setMimeType(mime_type)
        listitem.setContentLookup(False)
        if playlist.has_drm:
            license_url = playlist.widevine_license_url
            if not license_url:
                self._fail_play("no widevine license")
                return
            listitem.setProperty("inputstream.adaptive.license_type", "com.widevine.alpha")
            listitem.setProperty(
                "inputstream.adaptive.license_key",
                f"{license_url}|{LICENSE_HEADERS}|R{{SSM}}|",
            )
        if playlist.subtitles:
            listitem.setSubtitles(list(playlist.subtitles))
        xbmcplugin.setResolvedUrl(self.handle, True, listitem)

    def _load_playlist(self, product_id: int, video_type: str):
        try:
            return self.api.get_playlist(product_id, video_type)
        except ApiError:
            if video_type != "EPISODE":
                raise
            # Live Epika currently 404s videoType=EPISODE and serves episode
            # assets with videoType=MOVIE. Keep the planned type first.
            _log("episode playlist unavailable, retrying movie type", xbmc.LOGINFO)
            return self.api.get_playlist(product_id, "MOVIE")


def _select_stream(playlist) -> tuple[str | None, str | None, str | None]:
    if playlist.dash_url:
        return playlist.dash_url, "mpd", DASH_MIME
    if playlist.has_drm:
        return None, None, None
    if playlist.hls_url:
        return playlist.hls_url, "hls", HLS_MIME
    return None, None, None
