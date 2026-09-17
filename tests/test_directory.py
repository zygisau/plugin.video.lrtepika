# MIT License
"""Pure directory mapping, pagination, artwork, and playlist parsing."""

from __future__ import annotations

import json
from pathlib import Path

from resources.lib.directory import (
    PAGE_SIZE,
    find_section,
    has_next_page,
    map_item,
    parse_catalog_page,
    parse_item_list,
    parse_playlist,
    parse_sections,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_catalog_meta_envelope_and_pagination():
    page = parse_catalog_page(load_fixture("catalog_mixed.json"))
    assert page.total_count == 2
    assert page.first_result == 0
    assert page.page_size == PAGE_SIZE
    assert [item.type for item in page.items] == ["VOD", "SERIAL"]
    assert page.has_next is False

    first = parse_catalog_page(load_fixture("catalog_page_first.json"))
    assert first.has_next is True
    assert first.first_result == 0
    assert first.total_count == 45

    last = parse_catalog_page(load_fixture("catalog_page_last.json"))
    assert last.has_next is False
    assert last.first_result == 44
    assert len(last.items) == 1


def test_pagination_without_total_count_uses_page_size():
    assert has_next_page(0, 30, None, 30) is True
    assert has_next_page(0, 12, None, 30) is False
    assert has_next_page(0, 12, 40, 30) is True
    assert has_next_page(30, 10, 40, 30) is False


def test_item_kind_mappings_and_actual_metadata():
    page = parse_catalog_page(load_fixture("catalog_mixed.json"))
    vod, serial = page.items
    assert vod.media_type == "movie"
    assert vod.content == "movies"
    assert vod.is_playable is True
    assert vod.is_folder is False
    assert vod.plot == "Actual documentary plot"
    assert vod.genres == ("Dokumentiniai filmai", "Drama")
    assert vod.year == 2018
    assert vod.duration == 1522

    assert serial.media_type == "tvshow"
    assert serial.content == "tvshows"
    assert serial.is_playable is False
    assert serial.is_folder is True
    assert serial.plot == "Actual serial plot"
    assert serial.year == 2024

    seasons = parse_item_list(load_fixture("seasons.json"))
    assert [item.type for item in seasons] == ["SEASON", "SEASON"]
    assert seasons[0].media_type == "season"
    assert seasons[0].content == "seasons"
    assert seasons[0].season_number == 5
    assert seasons[0].is_folder is True

    episodes = parse_item_list(load_fixture("episodes.json"))
    episode = episodes[0]
    assert episode.type == "EPISODE"
    assert episode.media_type == "episode"
    assert episode.content == "episodes"
    assert episode.episode_number == 12
    assert episode.season_number == 5
    assert episode.is_playable is True


def test_malformed_records_are_skipped(caplog):
    page = parse_catalog_page(load_fixture("malformed_catalog.json"))
    assert [item.id for item in page.items] == [501, 503, 504]
    assert "unknown item type" in caplog.text
    missing_art = next(item for item in page.items if item.id == 501)
    assert missing_art.art["poster"] is None
    assert missing_art.art["thumb"] is None
    serial = next(item for item in page.items if item.id == 503)
    assert serial.art["poster"] is None
    assert serial.year == 2023


def test_protocol_relative_and_missing_art():
    page = parse_catalog_page(load_fixture("malformed_catalog.json"))
    protocol = next(item for item in page.items if item.id == 504)
    assert protocol.art["poster"] == "https://cdn.example.test/square.jpg"
    assert protocol.art["thumb"] == "https://cdn.example.test/square.jpg"

    mixed = parse_catalog_page(load_fixture("catalog_mixed.json"))
    vod = mixed.items[0]
    assert vod.art["poster"] == "https://cdn.example.test/doc-poster.jpg"
    assert vod.art["thumb"] == "https://cdn.example.test/doc-wide.jpg"
    assert vod.art["fanart"] == "https://cdn.example.test/doc-wide.jpg"


def test_section_elements_and_stable_id_lookup():
    sections = parse_sections(load_fixture("sections_main.json"))
    assert [section.id for section in sections] == [429461, 433059]
    featured = find_section(sections, "433059")
    assert featured is not None
    assert featured.title == "Series spotlight"
    assert featured.items[0].id == 2001
    assert featured.items[0].type == "SERIAL"
    assert find_section(sections, 0) is None

    filmai = parse_sections(load_fixture("sections_filmai.json"))
    top = find_section(filmai, 624215)
    assert top is not None
    assert top.items[0].title == "Top film"


def test_playlist_dash_drm_and_hls_forms():
    dash = parse_playlist(load_fixture("playlist_dash_drm.json"))
    assert dash is not None
    assert dash.dash_url == "https://cdn.example.test/movie.mpd"
    assert dash.hls_url == "https://cdn.example.test/movie.m3u8"
    assert dash.widevine_license_url == "https://license.example.test/widevine"
    assert dash.has_drm is True
    assert dash.subtitles == ("https://cdn.example.test/lt.vtt",)

    hls = parse_playlist(load_fixture("playlist_hls.json"))
    assert hls is not None
    assert hls.dash_url is None
    assert hls.hls_url == "https://cdn.example.test/free.m3u8"
    assert hls.has_drm is False
    assert parse_playlist("nope") is None


def test_map_item_ignores_invalid_year_and_blank_urls():
    item = map_item(
        {
            "id": 9,
            "type": "VOD",
            "title": "Odd",
            "lead": "Plot",
            "year": "not-a-year",
            "duration": True,
            "images": {"16x9": [{"url": "ftp://bad.example/file"}]},
        }
    )
    assert item is not None
    assert item.year is None
    assert item.duration is None
    assert item.art["thumb"] is None
