# MIT License
"""HTTP client contract for the thin LRT Epika API wrapper."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import pytest
import requests

from resources.lib.api import (
    DEFAULT_PAGE_SIZE,
    DEFAULT_TIMEOUT,
    TENANT_UID,
    ApiError,
    EpikaApi,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        if text is not None:
            self.text = text
        elif payload is not None:
            self.text = json.dumps(payload)
        else:
            self.text = ""

    def json(self):
        if self._payload is None:
            raise ValueError("No JSON object could be decoded")
        return self._payload


class RecordingSession:
    def __init__(self, response=None, error=None):
        self.response = response or FakeResponse(payload={})
        self.error = error
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": list(params or []), "timeout": timeout})
        if self.error is not None:
            raise self.error
        return self.response


def prepared_query(url, params):
    request = requests.Request("GET", url, params=params).prepare()
    parsed = urlparse(request.url)
    return request.url, parse_qsl(parsed.query, keep_blank_values=True)


def test_get_categories_path_and_defaults():
    session = RecordingSession(FakeResponse(payload=load_fixture("categories.json")))
    api = EpikaApi(session=session)
    payload = api.get_categories(268)
    assert payload[0]["id"] == 320
    call = session.calls[0]
    assert call["url"] == "https://epika.lrt.lt/api/items/categories"
    assert call["timeout"] == DEFAULT_TIMEOUT
    assert call["params"] == [
        ("lang", "LIT"),
        ("platform", "BROWSER"),
        ("mainCategoryId", 268),
    ]


def test_get_sections_path():
    session = RecordingSession(FakeResponse(payload=load_fixture("sections_main.json")))
    api = EpikaApi(session=session)
    api.get_sections("main")
    call = session.calls[0]
    assert call["url"].endswith("/products/sections/main")
    assert ("elementsLimit", DEFAULT_PAGE_SIZE) in call["params"]


def test_catalog_repeats_category_query_params():
    session = RecordingSession(FakeResponse(payload=load_fixture("catalog_mixed.json")))
    api = EpikaApi(session=session)
    api.get_catalog([268, 266], [320, 277], first_result=30, max_results=30)
    call = session.calls[0]
    assert call["url"].endswith("/products/vods")
    assert call["params"] == [
        ("lang", "LIT"),
        ("platform", "BROWSER"),
        ("firstResult", 30),
        ("maxResults", 30),
        ("mainCategoryId[]", 268),
        ("mainCategoryId[]", 266),
        ("categoryId[]", 320),
        ("categoryId[]", 277),
    ]
    url, query = prepared_query(call["url"], call["params"])
    assert query.count(("mainCategoryId[]", "268")) == 1
    assert query.count(("mainCategoryId[]", "266")) == 1
    assert query.count(("categoryId[]", "320")) == 1
    assert "mainCategoryId%5B%5D=268" in url
    assert "mainCategoryId%5B%5D=266" in url


def test_search_escapes_keyword_and_uses_item_type():
    session = RecordingSession(FakeResponse(payload=load_fixture("search_vod.json")))
    api = EpikaApi(session=session)
    keyword = "šokis & test"
    api.search("VOD", keyword, first_result=0, max_results=30)
    call = session.calls[0]
    assert call["url"] == "https://epika.lrt.lt/api/products/vods/search/VOD"
    assert ("keyword", keyword) in call["params"]
    url, query = prepared_query(call["url"], call["params"])
    assert ("keyword", keyword) in query
    assert "%26" in url
    assert "šokis" not in url


@pytest.mark.parametrize("item_type,fixture", [
    ("SERIAL", "search_serial.json"),
    ("EPISODE", "search_episode.json"),
])
def test_search_item_types(item_type, fixture):
    session = RecordingSession(FakeResponse(payload=load_fixture(fixture)))
    api = EpikaApi(session=session)
    api.search(item_type, "lita")
    assert session.calls[0]["url"].endswith(f"/products/vods/search/{item_type}")


def test_playlist_movie_versus_episode():
    session = RecordingSession(FakeResponse(payload=load_fixture("playlist_dash_drm.json")))
    api = EpikaApi(session=session)
    api.get_playlist(828554, "MOVIE")
    movie_call = session.calls[0]
    assert movie_call["url"] == "https://epika.lrt.lt/api/products/828554/videos/playlist"
    assert movie_call["params"] == [
        ("videoType", "MOVIE"),
        ("platform", "BROWSER"),
        ("tenantUid", TENANT_UID),
    ]

    session.response = FakeResponse(payload=load_fixture("playlist_hls.json"))
    api.get_playlist(911474, "EPISODE")
    episode_call = session.calls[1]
    assert episode_call["url"] == "https://epika.lrt.lt/api/products/911474/videos/playlist"
    assert ("videoType", "EPISODE") in episode_call["params"]
    assert ("tenantUid", TENANT_UID) in episode_call["params"]


def test_serial_and_episode_paths():
    session = RecordingSession(FakeResponse(payload=load_fixture("seasons.json")))
    api = EpikaApi(session=session)
    api.get_serial_seasons(1001665)
    assert session.calls[0]["url"].endswith("/products/vods/serials/1001665/seasons")
    session.response = FakeResponse(payload=load_fixture("episodes.json"))
    api.get_season_episodes(1001665, 1217612)
    assert session.calls[1]["url"].endswith(
        "/products/vods/serials/1001665/seasons/1217612/episodes"
    )


def test_timeout_becomes_api_error():
    session = RecordingSession(error=requests.Timeout("slow"))
    api = EpikaApi(session=session)
    with pytest.raises(ApiError) as caught:
        api.get_catalog([268])
    assert "timed out" in str(caught.value)
    assert "http" not in str(caught.value).lower() or "timed out" in str(caught.value)
    assert "license" not in str(caught.value).lower()


def test_http_error_is_safe():
    session = RecordingSession(FakeResponse(status_code=403, payload=load_fixture("error_payload.json")))
    api = EpikaApi(session=session)
    with pytest.raises(ApiError) as caught:
        api.get_product(1)
    assert caught.value.status == 403
    assert "HTTP 403" in str(caught.value)
    assert "Forbidden" not in str(caught.value)


def test_invalid_json_and_connection_errors():
    session = RecordingSession(FakeResponse(status_code=200, payload=None, text="{"))
    api = EpikaApi(session=session)
    with pytest.raises(ApiError) as caught:
        api.get_sections("filmai")
    assert "invalid JSON" in str(caught.value)

    session = RecordingSession(error=requests.ConnectionError("dns"))
    api = EpikaApi(session=session)
    with pytest.raises(ApiError) as caught:
        api.get_categories(268)
    assert "request failed" in str(caught.value)
    assert "dns" not in str(caught.value)


def test_rejects_unknown_search_and_playlist_types():
    api = EpikaApi(session=RecordingSession())
    with pytest.raises(ApiError):
        api.search("MOVIE", "x")
    with pytest.raises(ApiError):
        api.get_playlist(1, "VOD")
    with pytest.raises(ApiError):
        api.get_sections("titulinis")


@pytest.mark.live
def test_live_catalog_envelope_opt_in():
    if os.environ.get("LRT_EPIKA_LIVE") != "1":
        pytest.skip("set LRT_EPIKA_LIVE=1 for read-only live checks")
    api = EpikaApi()
    payload = api.get_catalog([268], first_result=0, max_results=1)
    assert isinstance(payload, dict)
    assert "items" in payload
    assert "meta" in payload
    assert "totalCount" in payload["meta"]


@pytest.mark.live
def test_live_search_envelope_opt_in():
    if os.environ.get("LRT_EPIKA_LIVE") != "1":
        pytest.skip("set LRT_EPIKA_LIVE=1 for read-only live checks")
    api = EpikaApi()
    payload = api.search("VOD", "lita", first_result=0, max_results=1)
    assert isinstance(payload, dict)
    assert "items" in payload
    assert "meta" in payload
    assert "totalCount" in payload["meta"]
