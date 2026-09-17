# MIT License
"""Epika share URL parser and API resolver contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import requests

from resources.lib.api import ApiError, EpikaApi
from resources.lib.send_reference import (
    EpikaUnavailableError,
    NotFoundError,
    UnsupportedProductError,
    UnsupportedUrlError,
    parse_epika_url,
    resolve_epika_url,
)

FIXTURES = Path(__file__).parent / "fixtures"

VOD_URL = "https://epika.lrt.lt/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,432486"
SERIAL_URL = "https://epika.lrt.lt/vaidybiniai-serialai,304/pazadas-odcinki,471378"
EPISODE_URL = "https://epika.lrt.lt/vaidybiniai-serialai,304/pazadas-odcinki,471378/odcinek-8,S04E08,1394661"
SEASON_URL = "https://epika.lrt.lt/vaidybiniai-serialai,304/4-sezonas-odcinki,471378/sezon-4,S04,1351060"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ScriptedLookup:
    def __init__(self):
        self.products = {
            432486: load_fixture("product_vod.json"),
            471378: load_fixture("product_serial.json"),
            1394661: load_fixture("product_episode.json"),
        }
        self.seasons = {1351060: load_fixture("season_detail.json")}
        self.product_errors = {}
        self.season_errors = {}
        self.calls = []

    def get_product(self, product_id):
        self.calls.append(("get_product", product_id))
        error = self.product_errors.get(product_id)
        if error is not None:
            raise error
        if product_id not in self.products:
            raise ApiError("get_product", "HTTP 404", status=404)
        return self.products[product_id]

    def get_season_detail(self, season_id):
        self.calls.append(("get_season_detail", season_id))
        error = self.season_errors.get(season_id)
        if error is not None:
            raise error
        if season_id not in self.seasons:
            raise ApiError("get_season_detail", "HTTP 404", status=404)
        return self.seasons[season_id]


def test_parse_four_canonical_kinds():
    assert parse_epika_url(VOD_URL).product_id == 432486
    assert parse_epika_url(VOD_URL).parent_id == 268
    assert parse_epika_url(SERIAL_URL).product_id == 471378
    episode = parse_epika_url(EPISODE_URL)
    assert episode.product_id == 1394661
    assert episode.parent_id == 471378
    season = parse_epika_url(SEASON_URL)
    assert season.product_id == 1351060
    assert season.parent_id == 471378


def test_resolve_four_kinds_and_plugin_actions():
    api = ScriptedLookup()
    vod = resolve_epika_url(VOD_URL, api)
    assert vod.kind == "VOD"
    assert vod.action == "play"
    assert vod.plugin_url.endswith("route=play&product_id=432486&item_type=VOD")
    serial = resolve_epika_url(SERIAL_URL, api)
    assert serial.kind == "SERIAL"
    assert serial.action == "browse"
    assert "route=serial" in serial.plugin_url
    assert "serial_id=471378" in serial.plugin_url
    episode = resolve_epika_url(EPISODE_URL, api)
    assert episode.kind == "EPISODE"
    assert episode.action == "play"
    assert episode.plugin_url.endswith("route=play&product_id=1394661&item_type=EPISODE")
    season = resolve_epika_url(SEASON_URL, api)
    assert season.kind == "SEASON"
    assert season.action == "browse"
    assert "route=episodes" in season.plugin_url
    assert "serial_id=471378" in season.plugin_url
    assert "season_id=1351060" in season.plugin_url
    assert api.calls == [
        ("get_product", 432486),
        ("get_product", 471378),
        ("get_product", 1394661),
        ("get_product", 1351060),
        ("get_season_detail", 1351060),
    ]


@pytest.mark.parametrize(
    "url",
    [
        "http://epika.lrt.lt/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,432486",
        "https://epika.lrt.lt.evil.example/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,432486",
        "https://user:pass@epika.lrt.lt/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,432486",
        "https://epika.lrt.lt:443/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,432486",
        "https://epika.lrt.lt/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,432486#frag",
        "https://epika.lrt.lt/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,432486?utm=1",
        "https://epika.lrt.lt/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,432486\\x",
        "https://epika.lrt.lt/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,432486\n",
        "https://127.0.0.1/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,432486",
        "https://epika.lrt.lt/",
        "https://epika.lrt.lt/filmai/drama,c299",
        "https://epika.lrt.lt/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,0432486",
        "https://epika.lrt.lt/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,0",
        "https://epika.lrt.lt/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,-1",
        "https://epika.lrt.lt/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,2147483648",
        "https://epika.lrt.lt/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,432486/",
        "ftp://epika.lrt.lt/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,432486",
        "https://epika.lrt.lt/adomas",
        "not-a-url",
        "",
        "https://" + ("epika.lrt.lt/" + "a" * 1024),
    ],
)
def test_parser_rejects_attack_and_malformed_urls(url):
    with pytest.raises(UnsupportedUrlError):
        parse_epika_url(url)


def test_parser_never_requires_network():
    class Forbidden:
        def get_product(self, product_id):
            raise AssertionError("parser must not call the API")

    with pytest.raises(UnsupportedUrlError):
        parse_epika_url("http://example.invalid/1")
    Forbidden()


def test_only_404_falls_back_to_season_detail():
    api = ScriptedLookup()
    resolve_epika_url(SEASON_URL, api)
    assert api.calls[-2:] == [("get_product", 1351060), ("get_season_detail", 1351060)]

    api = ScriptedLookup()
    api.product_errors[1351060] = ApiError("get_product", "timed out")
    with pytest.raises(EpikaUnavailableError):
        resolve_epika_url(SEASON_URL, api)
    assert api.calls == [("get_product", 1351060)]

    api = ScriptedLookup()
    api.product_errors[1351060] = ApiError("get_product", "HTTP 403", status=403)
    with pytest.raises(EpikaUnavailableError):
        resolve_epika_url(SEASON_URL, api)
    assert api.calls == [("get_product", 1351060)]

    api = ScriptedLookup()
    api.product_errors[1351060] = ApiError("get_product", "HTTP 500", status=500)
    with pytest.raises(EpikaUnavailableError):
        resolve_epika_url(SEASON_URL, api)
    assert ("get_season_detail", 1351060) not in api.calls

    api = ScriptedLookup()
    api.product_errors[1351060] = ApiError("get_product", "invalid JSON")
    with pytest.raises(EpikaUnavailableError):
        resolve_epika_url(SEASON_URL, api)
    assert ("get_season_detail", 1351060) not in api.calls


def test_missing_product_is_not_found():
    api = ScriptedLookup()
    with pytest.raises(NotFoundError):
        resolve_epika_url("https://epika.lrt.lt/missing,1", api)
    assert api.calls == [("get_product", 1), ("get_season_detail", 1)]


def test_type_disagreement_and_unknown_type_are_unsupported():
    api = ScriptedLookup()
    api.products[432486] = {**load_fixture("product_vod.json"), "type": "VOD", "type_": "SERIAL"}
    with pytest.raises(UnsupportedProductError):
        resolve_epika_url(VOD_URL, api)

    api = ScriptedLookup()
    api.products[432486] = {**load_fixture("product_vod.json"), "type": "CLIP", "type_": "CLIP"}
    with pytest.raises(UnsupportedProductError):
        resolve_epika_url(VOD_URL, api)


def test_type_fallback_when_primary_missing():
    api = ScriptedLookup()
    payload = dict(load_fixture("product_vod.json"))
    del payload["type"]
    api.products[432486] = payload
    resolved = resolve_epika_url(VOD_URL, api)
    assert resolved.kind == "VOD"


def test_response_id_and_weburl_must_agree():
    api = ScriptedLookup()
    api.products[432486] = {**load_fixture("product_vod.json"), "id": 99}
    with pytest.raises(UnsupportedProductError):
        resolve_epika_url(VOD_URL, api)

    api = ScriptedLookup()
    api.products[432486] = {
        **load_fixture("product_vod.json"),
        "webUrl": "https://epika.lrt.lt/other,1",
    }
    with pytest.raises(UnsupportedProductError):
        resolve_epika_url(VOD_URL, api)

    api = ScriptedLookup()
    api.products[432486] = {
        **load_fixture("product_vod.json"),
        "webUrl": "http://epika.lrt.lt/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,432486",
    }
    with pytest.raises(UnsupportedProductError):
        resolve_epika_url(VOD_URL, api)


def test_episode_and_season_require_nested_serial_parent():
    api = ScriptedLookup()
    wrong_parent = "https://epika.lrt.lt/vaidybiniai-serialai,304/other-odcinki,1/odcinek-8,S04E08,1394661"
    with pytest.raises(UnsupportedProductError):
        resolve_epika_url(wrong_parent, api)

    api = ScriptedLookup()
    payload = load_fixture("product_episode.json")
    payload = json.loads(json.dumps(payload))
    payload["season"]["serial"]["id"] = 1
    api.products[1394661] = payload
    with pytest.raises(UnsupportedProductError):
        resolve_epika_url(EPISODE_URL, api)

    api = ScriptedLookup()
    season = json.loads(json.dumps(load_fixture("season_detail.json")))
    season["serial"]["id"] = 9
    api.seasons[1351060] = season
    with pytest.raises(UnsupportedProductError):
        resolve_epika_url(SEASON_URL, api)


def test_timeout_on_season_fallback_is_unavailable():
    api = ScriptedLookup()
    api.season_errors[1351060] = ApiError("get_season_detail", "timed out")
    with pytest.raises(EpikaUnavailableError):
        resolve_epika_url(SEASON_URL, api)


def test_real_api_timeout_does_not_follow_submitted_url():
    class TrackingSession:
        def __init__(self):
            self.calls = []

        def get(self, url, params=None, timeout=None):
            self.calls.append(url)
            raise requests.Timeout("slow")

    session = TrackingSession()
    api = EpikaApi(session=session, timeout=(2.0, 4.0))
    with pytest.raises(EpikaUnavailableError):
        resolve_epika_url(VOD_URL, api)
    assert session.calls == ["https://epika.lrt.lt/api/products/vods/432486"]


@pytest.mark.live
def test_live_send_reference_kinds_opt_in():
    if os.environ.get("LRT_EPIKA_LIVE") != "1":
        pytest.skip("set LRT_EPIKA_LIVE=1 for read-only live checks")
    api = EpikaApi()
    vod = resolve_epika_url(VOD_URL, api)
    serial = resolve_epika_url(SERIAL_URL, api)
    episode = resolve_epika_url(EPISODE_URL, api)
    season = resolve_epika_url(SEASON_URL, api)
    assert (vod.kind, vod.action, vod.product_id) == ("VOD", "play", 432486)
    assert (serial.kind, serial.action, serial.product_id) == ("SERIAL", "browse", 471378)
    assert (episode.kind, episode.action, episode.product_id) == ("EPISODE", "play", 1394661)
    assert episode.serial_id == 471378
    assert (season.kind, season.action, season.product_id) == ("SEASON", "browse", 1351060)
    assert season.serial_id == 471378
    assert "route=play" in vod.plugin_url
    assert "route=serial" in serial.plugin_url
    assert "route=episodes" in season.plugin_url
