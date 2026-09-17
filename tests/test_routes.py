# MIT License
"""Pure plugin URI builders keep existing route semantics."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlparse

import pytest

from resources.lib.plugin import Plugin
from resources.lib.routes import (
    DEFAULT_BASE_URL,
    build_plugin_url,
    episodes_plugin_url,
    play_plugin_url,
    serial_plugin_url,
)


def query(url: str) -> dict[str, str]:
    return dict(parse_qsl(urlparse(url).query))


def test_build_plugin_url_matches_plugin_url_helper():
    plugin = Plugin(["plugin://plugin.video.lrtepika/", "1", ""])
    kwargs = {"route": "play", "product_id": 432486, "item_type": "VOD"}
    assert plugin.url(**kwargs) == build_plugin_url(plugin.base_url, **kwargs)
    assert plugin.url() == plugin.base_url
    assert build_plugin_url(DEFAULT_BASE_URL) == DEFAULT_BASE_URL


def test_play_serial_and_episodes_builders():
    play = play_plugin_url(432486, "VOD")
    assert play.startswith(DEFAULT_BASE_URL)
    assert query(play) == {"route": "play", "product_id": "432486", "item_type": "VOD"}
    episode = play_plugin_url(1394661, "EPISODE")
    assert query(episode) == {"route": "play", "product_id": "1394661", "item_type": "EPISODE"}
    serial = serial_plugin_url(471378, "Pažadas")
    assert query(serial) == {"route": "serial", "serial_id": "471378", "title": "Pažadas"}
    season = episodes_plugin_url(471378, 1351060, "4 sezonas")
    assert query(season) == {
        "route": "episodes",
        "serial_id": "471378",
        "season_id": "1351060",
        "title": "4 sezonas",
    }


def test_empty_title_is_omitted_like_plugin_item_urls():
    assert "title=" not in serial_plugin_url(471378, "")
    assert "title=" not in serial_plugin_url(471378, None)
    assert query(serial_plugin_url(471378, "Pažadas"))["title"] == "Pažadas"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"product_id": 0, "item_type": "VOD"},
        {"product_id": -1, "item_type": "VOD"},
        {"product_id": 2147483648, "item_type": "VOD"},
        {"product_id": True, "item_type": "VOD"},
        {"product_id": "432486", "item_type": "VOD"},
        {"product_id": 432486, "item_type": "SERIAL"},
        {"product_id": 432486, "item_type": "MOVIE"},
    ],
)
def test_play_builder_rejects_invalid_targets(kwargs):
    with pytest.raises(ValueError):
        play_plugin_url(**kwargs)


def test_container_builders_reject_invalid_ids():
    with pytest.raises(ValueError):
        serial_plugin_url(0)
    with pytest.raises(ValueError):
        episodes_plugin_url(471378, 0)
    with pytest.raises(ValueError):
        episodes_plugin_url(0, 1351060)
