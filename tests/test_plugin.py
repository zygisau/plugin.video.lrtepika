# MIT License
"""Route dispatcher, navigation, pagination, and playback contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import pytest

from resources.lib.api import ApiError
from resources.lib.directory import (
    MOVIE_MAIN_CATEGORIES,
    MOVIE_MAIN_CATEGORY_IDS,
    PAGE_SIZE,
    SERIES_MAIN_CATEGORIES,
    SERIES_MAIN_CATEGORY_IDS,
)
from resources.lib.history import load_history, save_history
from resources.lib.plugin import (
    NEW_SEARCH_LABEL,
    PLAY_ERROR_MESSAGE,
    Plugin,
    SEARCH_EMPTY_MESSAGE,
    SEARCH_LOOKAHEAD,
    run,
)
from conftest import FakeKeyboard, KODI

FIXTURES = Path(__file__).parent / "fixtures"
PLUGIN_URL = "plugin://plugin.video.lrtepika/"
HANDLE = 1


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def query(url: str) -> dict[str, str]:
    return dict(parse_qsl(urlparse(url).query))


def labels() -> list[str]:
    return [row["listitem"].label for row in KODI.directory_items]


def urls() -> list[str]:
    return [row["url"] for row in KODI.directory_items]


def queries() -> list[dict[str, str]]:
    return [query(url) for url in urls()]


def argv(raw: str = "") -> list[str]:
    if raw and not raw.startswith("?"):
        raw = "?" + raw
    return [PLUGIN_URL, str(HANDLE), raw]


class ScriptedApi:
    def __init__(self):
        self.calls = []
        self.error = None
        self.playlist_error = None
        self.section_payloads = {
            "main": load_fixture("sections_main.json"),
            "filmai": load_fixture("sections_filmai.json"),
            "serialai": load_fixture("sections_serialai.json"),
        }
        self.categories_payload = load_fixture("categories.json")
        self.catalog_payload = load_fixture("catalog_mixed.json")
        self.seasons_payload = load_fixture("seasons.json")
        self.episodes_payload = load_fixture("episodes.json")
        self.playlist_payload = load_fixture("playlist_dash_drm.json")
        self.playlist_payloads = {}
        self.search_payloads = {
            "VOD": load_fixture("search_vod.json"),
            "SERIAL": load_fixture("search_serial.json"),
            "EPISODE": load_fixture("search_episode.json"),
        }
        self.search_by_offset = {}
        self.search_errors = {}

    def _maybe_raise(self):
        if self.error is not None:
            raise self.error

    def get_sections(self, section_name, elements_limit=30):
        self.calls.append(("get_sections", {"section_name": section_name, "elements_limit": elements_limit}))
        self._maybe_raise()
        return self.section_payloads[section_name]

    def get_categories(self, main_category_id):
        self.calls.append(("get_categories", {"main_category_id": main_category_id}))
        self._maybe_raise()
        return self.categories_payload

    def get_catalog(self, main_category_ids, category_ids=None, first_result=0, max_results=30):
        self.calls.append(
            (
                "get_catalog",
                {
                    "main_category_ids": list(main_category_ids),
                    "category_ids": list(category_ids or []),
                    "first_result": first_result,
                    "max_results": max_results,
                },
            )
        )
        self._maybe_raise()
        return self.catalog_payload

    def get_serial_seasons(self, serial_id):
        self.calls.append(("get_serial_seasons", {"serial_id": serial_id}))
        self._maybe_raise()
        return self.seasons_payload

    def get_season_episodes(self, serial_id, season_id):
        self.calls.append(("get_season_episodes", {"serial_id": serial_id, "season_id": season_id}))
        self._maybe_raise()
        return self.episodes_payload

    def get_playlist(self, product_id, video_type):
        self.calls.append(("get_playlist", {"product_id": product_id, "video_type": video_type}))
        if self.playlist_error is not None:
            raise self.playlist_error
        self._maybe_raise()
        if video_type in self.playlist_payloads:
            payload = self.playlist_payloads[video_type]
            if isinstance(payload, Exception):
                raise payload
            return payload
        return self.playlist_payload

    def search(self, item_type, keyword, first_result=0, max_results=30):
        self.calls.append(
            (
                "search",
                {
                    "item_type": item_type,
                    "keyword": keyword,
                    "first_result": first_result,
                    "max_results": max_results,
                },
            )
        )
        error = self.search_errors.get(item_type)
        if error is not None:
            raise error
        self._maybe_raise()
        key = (item_type, first_result)
        if key in self.search_by_offset:
            return self.search_by_offset[key]
        if item_type in self.search_payloads:
            return self.search_payloads[item_type]
        return {"meta": {"totalCount": 0, "firstResult": first_result, "maxResults": max_results}, "items": []}


def run_plugin(raw: str = "", api: ScriptedApi | None = None, history_path=None) -> ScriptedApi:
    api = api or ScriptedApi()
    run(argv(raw), api=api, history_path=history_path)
    return api


def ended_once(succeeded: bool) -> None:
    assert KODI.end_of_directory_calls == [
        {
            "handle": HANDLE,
            "succeeded": succeeded,
            "update_listing": False,
            "cache_to_disc": False,
        }
    ]


def resolved_once(succeeded: bool) -> None:
    assert len(KODI.resolved) == 1
    assert KODI.resolved[0]["handle"] == HANDLE
    assert KODI.resolved[0]["succeeded"] is succeeded
    assert KODI.end_of_directory_calls == []


def logs_are_safe() -> None:
    joined = "\n".join(message for _level, message in KODI.logs)
    assert "license.example.test" not in joined
    assert "cdn.example.test" not in joined
    assert "R{SSM}" not in joined


def test_root_order_and_urls():
    run_plugin("")
    ended_once(True)
    assert labels() == ["Featured", "Movies", "Series", "Search"]
    assert [row["is_folder"] for row in KODI.directory_items] == [True, True, True, True]
    assert queries() == [
        {"route": "featured", "section_name": "main"},
        {"route": "movies"},
        {"route": "series"},
        {"route": "search"},
    ]
    assert all("route=root" not in url for url in urls())
    assert KODI.plugin_category == "LRT Epika"
    assert KODI.sort_methods == []


def test_featured_uses_stable_section_id():
    api = run_plugin("route=featured&section_name=main")
    ended_once(True)
    assert api.calls == [("get_sections", {"section_name": "main", "elements_limit": PAGE_SIZE})]
    assert labels() == ["Featured row", "Series spotlight"]
    assert queries() == [
        {"route": "section", "section_name": "main", "section_id": "429461", "title": "Featured row"},
        {"route": "section", "section_name": "main", "section_id": "433059", "title": "Series spotlight"},
    ]
    assert all("section_id=0" not in url for url in urls())

    KODI.directory_items.clear()
    KODI.end_of_directory_calls.clear()
    api = ScriptedApi()
    run_plugin("route=section&section_name=main&section_id=433059", api)
    ended_once(True)
    assert api.calls[0][0] == "get_sections"
    assert labels() == ["Featured serial"]
    item = KODI.directory_items[0]
    assert item["is_folder"] is True
    assert item["listitem"].getVideoInfoTag().media_type == "tvshow"
    assert query(item["url"]) == {"route": "serial", "serial_id": "2001", "title": "Featured serial"}


def test_movie_and_series_hubs_and_genre_filters():
    api = run_plugin("route=movies")
    assert labels() == ["Featured", "All"] + [label for _cid, label in MOVIE_MAIN_CATEGORIES]
    assert queries()[0] == {"route": "featured", "section_name": "filmai", "title": "Featured"}
    assert queries()[1]["route"] == "catalog"
    assert queries()[1]["main_ids"] == ",".join(str(cid) for cid in MOVIE_MAIN_CATEGORY_IDS)
    assert queries()[2] == {"route": "genres", "main_id": "268", "title": "Movies"}

    KODI.directory_items.clear()
    KODI.end_of_directory_calls.clear()
    run_plugin("route=series")
    assert labels() == ["Featured", "All"] + [label for _cid, label in SERIES_MAIN_CATEGORIES]
    assert queries()[0]["section_name"] == "serialai"
    assert queries()[1]["main_ids"] == ",".join(str(cid) for cid in SERIES_MAIN_CATEGORY_IDS)
    assert queries()[2] == {"route": "genres", "main_id": "304", "title": "Series"}

    KODI.directory_items.clear()
    KODI.end_of_directory_calls.clear()
    api = run_plugin("route=genres&main_id=268&title=Movies")
    assert api.calls[-1] == ("get_categories", {"main_category_id": 268})
    assert labels()[0] == "All"
    assert query(urls()[0]) == {"route": "catalog", "main_ids": "268", "title": "All"}
    assert labels()[1:] == ["Detektyvas", "Komedija", "Drama"]
    assert query(urls()[1])["category_id"] == "320"

    KODI.directory_items.clear()
    KODI.end_of_directory_calls.clear()
    api = ScriptedApi()
    run_plugin("route=catalog&main_ids=268&category_id=320&title=Detektyvas", api)
    assert api.calls[-1] == (
        "get_catalog",
        {
            "main_category_ids": [268],
            "category_ids": [320],
            "first_result": 0,
            "max_results": PAGE_SIZE,
        },
    )
    ended_once(True)
    assert KODI.content == "movies"


def test_catalog_pagination_next_stays_last():
    api = ScriptedApi()
    api.catalog_payload = load_fixture("catalog_page_first.json")
    run_plugin("route=catalog&main_ids=268,266,367,410", api)
    ended_once(True)
    assert labels()[-1] == "Next page"
    assert KODI.directory_items[-1]["is_folder"] is True
    assert KODI.directory_items[-1]["listitem"].properties.get("SpecialSort") == "bottom"
    next_query = query(urls()[-1])
    assert next_query["route"] == "catalog"
    assert next_query["first_result"] == "30"
    assert next_query["main_ids"] == "268,266,367,410"
    assert KODI.sort_methods == []

    KODI.directory_items.clear()
    KODI.end_of_directory_calls.clear()
    api.catalog_payload = load_fixture("catalog_page_last.json")
    run_plugin("route=catalog&main_ids=268&first_result=44", api)
    assert "Next page" not in labels()
    assert labels() == ["Last item"]


def test_gustavo_animation_catalog_routes_vods_not_serials():
    api = ScriptedApi()
    api.catalog_payload = load_fixture("catalog_gustavo_animation.json")
    run_plugin("route=catalog&main_ids=268&category_id=307", api)
    ended_once(True)
    assert api.calls == [
        (
            "get_catalog",
            {
                "main_category_ids": [268],
                "category_ids": [307],
                "first_result": 0,
                "max_results": PAGE_SIZE,
            },
        )
    ]
    assert all(name != "get_serial_seasons" for name, _params in api.calls)
    assert labels() == ["Gustavo nuotykiai", "Kaimiečiai"]
    assert [row["is_folder"] for row in KODI.directory_items] == [False, False]
    assert [row["listitem"].properties.get("IsPlayable") for row in KODI.directory_items] == [
        "true",
        "true",
    ]
    assert queries() == [
        {"route": "play", "product_id": "429850", "item_type": "VOD"},
        {"route": "play", "product_id": "946618", "item_type": "VOD"},
    ]
    assert KODI.content == "movies"


def test_serial_season_episode_urls_flags_and_media_types():
    api = run_plugin("route=catalog&main_ids=304")
    assert KODI.content == "tvshows"
    vod, serial = KODI.directory_items
    vod_info = vod["listitem"].getVideoInfoTag()
    serial_info = serial["listitem"].getVideoInfoTag()
    assert vod["is_folder"] is False
    assert vod["listitem"].properties.get("IsPlayable") == "true"
    assert vod_info.media_type == "movie"
    assert vod_info.plot == "Actual documentary plot"
    assert vod_info.year == 2018
    assert vod_info.duration == 1522
    assert vod_info.genres == ["Dokumentiniai filmai", "Drama"]
    assert query(vod["url"]) == {"route": "play", "product_id": "828554", "item_type": "VOD"}
    assert serial["is_folder"] is True
    assert serial["listitem"].properties.get("IsPlayable") is None
    assert serial_info.media_type == "tvshow"
    assert query(serial["url"])["route"] == "serial"
    assert query(serial["url"])["serial_id"] == "1001665"

    KODI.directory_items.clear()
    KODI.end_of_directory_calls.clear()
    run_plugin("route=serial&serial_id=1001665&title=Law%20firm", api)
    assert KODI.content == "seasons"
    assert [row["is_folder"] for row in KODI.directory_items] == [True, True]
    first_season = KODI.directory_items[0]
    assert first_season["listitem"].getVideoInfoTag().media_type == "season"
    assert first_season["listitem"].getVideoInfoTag().season == 5
    assert query(first_season["url"]) == {
        "route": "episodes",
        "serial_id": "1001665",
        "season_id": "1217612",
        "title": "5 sezonas",
    }

    KODI.directory_items.clear()
    KODI.end_of_directory_calls.clear()
    run_plugin("route=episodes&serial_id=1001665&season_id=1217612", api)
    assert KODI.content == "episodes"
    episode = KODI.directory_items[0]
    info = episode["listitem"].getVideoInfoTag()
    assert episode["is_folder"] is False
    assert episode["listitem"].properties.get("IsPlayable") == "true"
    assert info.media_type == "episode"
    assert info.season == 5
    assert info.episode == 12
    assert query(episode["url"]) == {"route": "play", "product_id": "1263987", "item_type": "EPISODE"}


def test_valid_empty_directory_succeeds_once():
    api = ScriptedApi()
    api.catalog_payload = {"meta": {"totalCount": 0, "firstResult": 0, "maxResults": 30}, "items": []}
    run_plugin("route=catalog&main_ids=268", api)
    ended_once(True)
    assert KODI.directory_items == []
    assert len(KODI.notifications) == 1
    assert KODI.notifications[0]["icon"] == "info"
    assert "No titles" in KODI.notifications[0]["message"]


def test_api_error_ends_failed_exactly_once():
    api = ScriptedApi()
    api.error = ApiError("get_catalog", "timed out")
    run_plugin("route=catalog&main_ids=268", api)
    ended_once(False)
    assert KODI.directory_items == []
    assert len(KODI.notifications) == 1
    assert KODI.notifications[0]["icon"] == "error"
    assert KODI.resolved == []
    assert sum("timed out" in message for _level, message in KODI.logs) == 1


def test_malformed_items_are_isolated():
    api = ScriptedApi()
    api.catalog_payload = load_fixture("malformed_catalog.json")
    run_plugin("route=catalog&main_ids=268", api)
    ended_once(True)
    assert labels() == ["Good movie", "Empty art serial", "Protocol art"]
    assert [query(url)["product_id" if "product_id" in query(url) else "serial_id"] for url in urls()] == [
        "501",
        "503",
        "504",
    ]
    serial = KODI.directory_items[1]
    assert serial["is_folder"] is True
    assert serial["listitem"].art.get("poster") is None or "poster" not in {
        key: value for key, value in serial["listitem"].art.items() if value
    }


def search_envelope(item_type: str, count: int, start_id: int = 1, total_count=None) -> dict:
    items = []
    for index in range(count):
        item_id = start_id + index
        record = {
            "id": item_id,
            "title": f"{item_type} {item_id}",
            "lead": "Search hit",
            "type": item_type,
            "year": 2025,
        }
        if item_type == "EPISODE":
            record["fullTitle"] = f"Show / {record['title']}"
            record["number"] = index + 1
        items.append(record)
    return {
        "meta": {
            "totalCount": count if total_count is None else total_count,
            "firstResult": 0,
            "maxResults": SEARCH_LOOKAHEAD,
        },
        "items": items,
    }


def empty_search(item_type: str) -> dict:
    return search_envelope(item_type, 0, total_count=0)


def search_calls(keyword: str, first_result=0, types=("VOD", "SERIAL", "EPISODE")):
    return [
        (
            "search",
            {
                "item_type": item_type,
                "keyword": keyword,
                "first_result": first_result if not isinstance(first_result, dict) else first_result[item_type],
                "max_results": SEARCH_LOOKAHEAD,
            },
        )
        for item_type in types
    ]


def test_search_menu_labels_and_urls(tmp_path):
    history_path = tmp_path / "search_history.json"
    run_plugin("route=search", history_path=history_path)
    ended_once(True)
    assert labels() == [NEW_SEARCH_LABEL]
    assert queries() == [{"route": "search_new"}]
    assert [row["is_folder"] for row in KODI.directory_items] == [True]
    assert FakeKeyboard.instances == []
    assert KODI.notifications == []
    assert KODI.plugin_category == "Search"
    assert KODI.content == "files"

    KODI.directory_items.clear()
    KODI.end_of_directory_calls.clear()
    save_history(history_path, ["lita", "šokis"])
    run_plugin("route=search", history_path=history_path)
    ended_once(True)
    assert labels() == [NEW_SEARCH_LABEL, "lita", "šokis"]
    assert queries() == [
        {"route": "search_new"},
        {"route": "search_results", "keyword": "lita"},
        {"route": "search_results", "keyword": "šokis"},
    ]


def test_search_keyboard_confirm_saves_and_shows_results(tmp_path):
    history_path = tmp_path / "search_history.json"
    FakeKeyboard.next_confirmed = True
    FakeKeyboard.next_text = "  Lita "
    api = run_plugin("route=search_new", history_path=history_path)
    ended_once(True)
    keyboard = FakeKeyboard.instances[0]
    assert keyboard.default == ""
    assert keyboard.heading == "Search"
    assert keyboard.hidden is False
    assert load_history(history_path) == ["Lita"]
    assert api.calls == search_calls("Lita")
    assert labels() == ["Search vod", "Search serial", "Search episode"]


def test_search_keyboard_cancel_and_blank_return_menu(tmp_path):
    history_path = tmp_path / "search_history.json"
    FakeKeyboard.next_confirmed = False
    FakeKeyboard.next_text = "Lita"
    api = run_plugin("route=search_new", history_path=history_path)
    ended_once(True)
    assert api.calls == []
    assert not history_path.exists()
    assert labels() == [NEW_SEARCH_LABEL]
    assert KODI.notifications == []

    KODI.directory_items.clear()
    KODI.end_of_directory_calls.clear()
    FakeKeyboard.instances.clear()
    FakeKeyboard.next_confirmed = True
    FakeKeyboard.next_text = " \t "
    api = run_plugin("route=search_new", history_path=history_path)
    ended_once(True)
    assert api.calls == []
    assert not history_path.exists()
    assert labels() == [NEW_SEARCH_LABEL]
    assert KODI.notifications == []


def test_search_results_blank_keyword_returns_menu(tmp_path):
    history_path = tmp_path / "search_history.json"
    api = run_plugin("route=search_results&keyword=", history_path=history_path)
    ended_once(True)
    assert api.calls == []
    assert labels() == [NEW_SEARCH_LABEL]
    assert KODI.notifications == []


def test_recent_search_does_not_rewrite_history(tmp_path):
    history_path = tmp_path / "search_history.json"
    save_history(history_path, ["alpha", "beta"])
    api = run_plugin("route=search_results&keyword=beta", history_path=history_path)
    ended_once(True)
    assert load_history(history_path) == ["alpha", "beta"]
    assert api.calls == search_calls("beta")
    assert labels() == ["Search vod", "Search serial", "Search episode"]


def test_search_typed_routes_flags_and_lookahead_calls(tmp_path):
    history_path = tmp_path / "search_history.json"
    api = run_plugin("route=search_results&keyword=lita", history_path=history_path)
    ended_once(True)
    assert api.calls == search_calls("lita")
    assert KODI.content == "videos"
    vod, serial, episode = KODI.directory_items
    assert vod["is_folder"] is False
    assert vod["listitem"].properties.get("IsPlayable") == "true"
    assert vod["listitem"].getVideoInfoTag().media_type == "movie"
    assert query(vod["url"]) == {"route": "play", "product_id": "890885", "item_type": "VOD"}
    assert serial["is_folder"] is True
    assert serial["listitem"].properties.get("IsPlayable") is None
    assert serial["listitem"].getVideoInfoTag().media_type == "tvshow"
    assert query(serial["url"]) == {"route": "serial", "serial_id": "911472", "title": "Search serial"}
    assert episode["is_folder"] is False
    assert episode["listitem"].properties.get("IsPlayable") == "true"
    assert episode["listitem"].getVideoInfoTag().media_type == "episode"
    assert query(episode["url"]) == {"route": "play", "product_id": "911474", "item_type": "EPISODE"}


def test_search_independent_offsets_and_exhausted_state(tmp_path):
    history_path = tmp_path / "search_history.json"
    api = ScriptedApi()
    api.search_by_offset = {
        ("VOD", 0): search_envelope("VOD", 31, start_id=1, total_count=31),
        ("SERIAL", 0): search_envelope("SERIAL", 5, start_id=100, total_count=5),
        ("EPISODE", 0): search_envelope("EPISODE", 31, start_id=200, total_count=31),
        ("VOD", 30): search_envelope("VOD", 4, start_id=31, total_count=4),
        ("EPISODE", 30): search_envelope("EPISODE", 2, start_id=231, total_count=2),
    }
    run_plugin("route=search_results&keyword=lita", api, history_path)
    ended_once(True)
    assert api.calls == search_calls("lita")
    assert labels()[:3] == ["VOD 1", "VOD 2", "VOD 3"]
    assert "VOD 30" in labels()
    assert "VOD 31" not in labels()
    assert "SERIAL 100" in labels()
    assert "SERIAL 104" in labels()
    assert labels()[-4:-1] == ["Show / EPISODE 227", "Show / EPISODE 228", "Show / EPISODE 229"]
    assert labels()[-1] == "Next page"
    assert KODI.directory_items[-1]["is_folder"] is True
    assert KODI.directory_items[-1]["listitem"].properties.get("SpecialSort") == "bottom"
    next_query = query(urls()[-1])
    assert next_query == {
        "route": "search_results",
        "keyword": "lita",
        "vod_offset": "30",
        "serial_offset": "-1",
        "episode_offset": "30",
    }

    KODI.directory_items.clear()
    KODI.end_of_directory_calls.clear()
    api.calls.clear()
    run_plugin(
        "route=search_results&keyword=lita&vod_offset=30&serial_offset=-1&episode_offset=30",
        api,
        history_path,
    )
    ended_once(True)
    assert api.calls == search_calls("lita", {"VOD": 30, "SERIAL": 30, "EPISODE": 30}, types=("VOD", "EPISODE"))
    assert "Next page" not in labels()
    assert labels()[0] == "VOD 31"
    assert labels()[-1] == "Show / EPISODE 232"


def test_search_deduplicates_type_and_id_on_rendered_page(tmp_path):
    history_path = tmp_path / "search_history.json"
    api = ScriptedApi()
    duplicate = search_envelope("VOD", 1, start_id=7)
    duplicate["items"].append(dict(duplicate["items"][0], title="Duplicate vod"))
    api.search_payloads = {
        "VOD": duplicate,
        "SERIAL": search_envelope("SERIAL", 1, start_id=7),
        "EPISODE": empty_search("EPISODE"),
    }
    run_plugin("route=search_results&keyword=dup", api, history_path)
    ended_once(True)
    assert labels() == ["VOD 7", "SERIAL 7"]
    assert queries() == [
        {"route": "play", "product_id": "7", "item_type": "VOD"},
        {"route": "serial", "serial_id": "7", "title": "SERIAL 7"},
    ]


def test_search_empty_and_error_behavior(tmp_path):
    history_path = tmp_path / "search_history.json"
    api = ScriptedApi()
    api.search_payloads = {
        "VOD": empty_search("VOD"),
        "SERIAL": empty_search("SERIAL"),
        "EPISODE": empty_search("EPISODE"),
    }
    run_plugin("route=search_results&keyword=zzz", api, history_path)
    ended_once(True)
    assert api.calls == search_calls("zzz")
    assert KODI.directory_items == []
    assert len(KODI.notifications) == 1
    assert KODI.notifications[0]["icon"] == "info"
    assert KODI.notifications[0]["message"] == SEARCH_EMPTY_MESSAGE

    KODI.directory_items.clear()
    KODI.end_of_directory_calls.clear()
    KODI.notifications.clear()
    api = ScriptedApi()
    api.error = ApiError("search", "timed out")
    run_plugin("route=search_results&keyword=lita", api, history_path)
    ended_once(False)
    assert api.calls == search_calls("lita")
    assert KODI.directory_items == []
    assert KODI.notifications[0]["icon"] == "error"
    assert sum("timed out" in message for _level, message in KODI.logs) == 1


def test_history_write_failure_logs_without_path(tmp_path, monkeypatch):
    history_path = tmp_path / "secret-history.json"

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("resources.lib.plugin.add_history", boom)
    FakeKeyboard.next_confirmed = True
    FakeKeyboard.next_text = "lita"
    api = run_plugin("route=search_new", history_path=history_path)
    ended_once(True)
    assert api.calls == search_calls("lita")
    assert labels() == ["Search vod", "Search serial", "Search episode"]
    joined = "\n".join(message for _level, message in KODI.logs)
    assert "unable to save search history" in joined
    assert "secret-history" not in joined
    assert str(history_path) not in joined


def test_injected_and_default_history_paths(tmp_path):
    injected = tmp_path / "custom.json"
    plugin = Plugin(argv("route=search"), history_path=injected)
    assert plugin.history_path == injected
    empty = Plugin(argv("route=search"), history_path="  ")
    assert empty.history_path is None
    default = Plugin(argv("route=search"))
    assert default.history_path == Path(__file__).resolve().parents[1] / "tests" / "_profile" / "search_history.json"


def test_vod_playlist_uses_movie_and_dash_drm_properties():
    api = run_plugin("route=play&product_id=828554&item_type=VOD")
    resolved_once(True)
    assert api.calls == [("get_playlist", {"product_id": 828554, "video_type": "MOVIE"})]
    item = KODI.resolved[0]["listitem"]
    assert item.path == "https://cdn.example.test/movie.mpd"
    assert item.mime_type == "application/dash+xml"
    assert item.content_lookup is False
    assert item.properties["inputstream"] == "inputstream.adaptive"
    assert item.properties["inputstream.adaptive.manifest_type"] == "mpd"
    assert item.properties["inputstream.adaptive.license_type"] == "com.widevine.alpha"
    assert item.properties["inputstream.adaptive.license_key"] == (
        "https://license.example.test/widevine|Content-Type=application/octet-stream|R{SSM}|"
    )
    assert item.subtitles == ["https://cdn.example.test/lt.vtt"]
    logs_are_safe()
    assert len(KODI.notifications) == 0


def test_episode_playlist_uses_episode_type():
    api = ScriptedApi()
    api.playlist_payload = load_fixture("playlist_hls.json")
    run_plugin("route=play&product_id=1263987&item_type=EPISODE", api)
    resolved_once(True)
    assert api.calls == [("get_playlist", {"product_id": 1263987, "video_type": "EPISODE"})]


def test_episode_playlist_retries_movie_after_episode_error():
    api = ScriptedApi()
    api.playlist_payloads = {
        "EPISODE": ApiError("get_playlist", "HTTP 404", status=404),
        "MOVIE": load_fixture("playlist_dash_drm.json"),
    }
    run_plugin("route=play&product_id=1263987&item_type=EPISODE", api)
    resolved_once(True)
    assert api.calls == [
        ("get_playlist", {"product_id": 1263987, "video_type": "EPISODE"}),
        ("get_playlist", {"product_id": 1263987, "video_type": "MOVIE"}),
    ]
    item = KODI.resolved[0]["listitem"]
    assert item.path == "https://cdn.example.test/movie.mpd"
    assert item.properties["inputstream.adaptive.license_type"] == "com.widevine.alpha"
    logs_are_safe()


def test_non_drm_hls_fallback():
    api = ScriptedApi()
    api.playlist_payload = load_fixture("playlist_hls.json")
    run_plugin("route=play&product_id=9&item_type=VOD", api)
    resolved_once(True)
    item = KODI.resolved[0]["listitem"]
    assert item.path == "https://cdn.example.test/free.m3u8"
    assert item.mime_type == "application/vnd.apple.mpegurl"
    assert item.properties["inputstream.adaptive.manifest_type"] == "hls"
    assert "inputstream.adaptive.license_key" not in item.properties
    assert "inputstream.adaptive.license_type" not in item.properties
    logs_are_safe()


def test_invalid_kind_and_missing_stream_resolve_false_once():
    api = run_plugin("route=play&product_id=1001665&item_type=SERIAL")
    resolved_once(False)
    assert api.calls == []
    assert len(KODI.notifications) == 1
    assert KODI.notifications[0]["message"] == PLAY_ERROR_MESSAGE
    logs_are_safe()

    KODI.resolved.clear()
    KODI.notifications.clear()
    KODI.logs.clear()
    api = ScriptedApi()
    api.playlist_payload = {"sources": {}, "drm": {}, "subtitles": []}
    run_plugin("route=play&product_id=1&item_type=VOD", api)
    resolved_once(False)
    assert api.calls == [("get_playlist", {"product_id": 1, "video_type": "MOVIE"})]
    assert len(KODI.notifications) == 1
    logs_are_safe()


def test_drm_without_dash_fails_closed():
    api = ScriptedApi()
    api.playlist_payload = {
        "sources": {"HLS": [{"src": "https://cdn.example.test/protected.m3u8"}]},
        "drm": {"WIDEVINE": {"src": "https://license.example.test/widevine"}},
        "subtitles": [],
    }
    run_plugin("route=play&product_id=2&item_type=VOD", api)
    resolved_once(False)
    logs_are_safe()


@pytest.mark.live
def test_live_featured_listing_opt_in():
    if os.environ.get("LRT_EPIKA_LIVE") != "1":
        pytest.skip("set LRT_EPIKA_LIVE=1 for read-only live checks")
    run(argv("route=featured&section_name=main"))
    ended_once(True)
    assert labels()
    for row in KODI.directory_items:
        assert row["is_folder"] is True
        assert "section_id" in query(row["url"])


@pytest.mark.live
def test_live_search_results_opt_in(tmp_path):
    if os.environ.get("LRT_EPIKA_LIVE") != "1":
        pytest.skip("set LRT_EPIKA_LIVE=1 for read-only live checks")
    history_path = tmp_path / "search_history.json"
    run(argv("route=search"), history_path=history_path)
    ended_once(True)
    assert labels()[0] == NEW_SEARCH_LABEL

    KODI.directory_items.clear()
    KODI.end_of_directory_calls.clear()
    KODI.notifications.clear()
    run(argv("route=search_results&keyword=lita"), history_path=history_path)
    ended_once(True)
    assert KODI.content == "videos"
    if not KODI.directory_items:
        assert KODI.notifications[0]["message"] == SEARCH_EMPTY_MESSAGE
    else:
        assert labels()
        assert load_history(history_path) == []
