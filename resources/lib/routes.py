# MIT License
"""Pure plugin URI builders for LRT Epika routes."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

ADDON_ID = "plugin.video.lrtepika"
DEFAULT_BASE_URL = f"plugin://{ADDON_ID}/"
MAX_ID = 2147483647
PLAYABLE_TYPES = ("VOD", "EPISODE")


def build_plugin_url(base_url: str, **kwargs: Any) -> str:
    """Build a plugin URL. None values are omitted; remaining values are encoded."""
    params = [(key, value) for key, value in kwargs.items() if value is not None]
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _require_id(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"invalid {name}")
    if value < 1 or value > MAX_ID:
        raise ValueError(f"invalid {name}")
    return value


def play_plugin_url(
    product_id: int,
    item_type: str,
    base_url: str = DEFAULT_BASE_URL,
) -> str:
    pid = _require_id(product_id, "product_id")
    if item_type not in PLAYABLE_TYPES:
        raise ValueError("invalid item_type")
    return build_plugin_url(base_url, route="play", product_id=pid, item_type=item_type)


def serial_plugin_url(
    serial_id: int,
    title: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
) -> str:
    sid = _require_id(serial_id, "serial_id")
    label = title if isinstance(title, str) and title else None
    return build_plugin_url(base_url, route="serial", serial_id=sid, title=label)


def episodes_plugin_url(
    serial_id: int,
    season_id: int,
    title: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
) -> str:
    sid = _require_id(serial_id, "serial_id")
    season = _require_id(season_id, "season_id")
    label = title if isinstance(title, str) and title else None
    return build_plugin_url(
        base_url,
        route="episodes",
        serial_id=sid,
        season_id=season,
        title=label,
    )
