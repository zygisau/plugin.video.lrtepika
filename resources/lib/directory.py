# MIT License
"""Pure parsing and view-model helpers for LRT Epika listings."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

LOGGER = logging.getLogger(__name__)

PAGE_SIZE = 30

MOVIE_MAIN_CATEGORIES: tuple[tuple[int, str], ...] = (
    (268, "Movies"),
    (266, "Documentary films"),
    (367, "Animation"),
    (410, "Kids"),
)
SERIES_MAIN_CATEGORIES: tuple[tuple[int, str], ...] = (
    (304, "Series"),
    (303, "Documentary series"),
    (474, "Animated series"),
    (322, "Kids series"),
)
MOVIE_MAIN_CATEGORY_IDS: tuple[int, ...] = tuple(item[0] for item in MOVIE_MAIN_CATEGORIES)
SERIES_MAIN_CATEGORY_IDS: tuple[int, ...] = tuple(item[0] for item in SERIES_MAIN_CATEGORIES)

FEATURED_SECTION = "main"
MOVIES_FEATURED_SECTION = "filmai"
SERIES_FEATURED_SECTION = "serialai"

TYPE_META = {
    "VOD": {"content": "movies", "media_type": "movie", "is_playable": True, "is_folder": False},
    "SERIAL": {"content": "tvshows", "media_type": "tvshow", "is_playable": False, "is_folder": True},
    "SEASON": {"content": "seasons", "media_type": "season", "is_playable": False, "is_folder": True},
    "EPISODE": {"content": "episodes", "media_type": "episode", "is_playable": True, "is_folder": False},
}

POSTER_RATIOS = ("3x4", "16x9", "1x1")
LANDSCAPE_RATIOS = ("16x9", "3x4", "1x1")


@dataclass(frozen=True)
class DirectoryItem:
    id: int
    type: str
    title: str
    plot: str
    year: int | None
    duration: int | None
    genres: tuple[str, ...]
    season_number: int | None
    episode_number: int | None
    art: dict[str, str | None]
    content: str
    media_type: str
    is_playable: bool
    is_folder: bool


@dataclass(frozen=True)
class SectionView:
    id: int
    title: str
    items: tuple[DirectoryItem, ...]


@dataclass(frozen=True)
class CatalogPage:
    items: tuple[DirectoryItem, ...]
    first_result: int
    page_size: int
    total_count: int | None
    has_next: bool


@dataclass(frozen=True)
class SearchPage:
    items: tuple[DirectoryItem, ...]
    first_result: int
    page_size: int
    has_next: bool


@dataclass(frozen=True)
class PlaylistView:
    dash_url: str | None
    hls_url: str | None
    widevine_license_url: str | None
    has_drm: bool
    subtitles: tuple[str, ...]


def normalize_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    lowered = url.lower()
    if lowered.startswith("https://") or lowered.startswith("http://"):
        return url
    return None


def coerce_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("-"):
            digits = text[1:]
            if digits.isdigit():
                return int(text)
        elif text.isdigit():
            return int(text)
    return None


def has_next_page(
    first_result: int,
    returned_count: int,
    total_count: int | None,
    page_size: int,
) -> bool:
    if total_count is not None:
        return first_result + returned_count < total_count
    return returned_count == page_size and returned_count > 0


def _first_image_url(images: Mapping[str, Any], preferred: Sequence[str]) -> str | None:
    for ratio in preferred:
        url = _url_from_entries(images.get(ratio))
        if url:
            return url
    for key, entries in images.items():
        if key in preferred:
            continue
        url = _url_from_entries(entries)
        if url:
            return url
    return None


def _url_from_entries(entries: Any) -> str | None:
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        url = normalize_url(entry.get("url"))
        if url:
            return url
    return None


def artwork_from_item(item: Mapping[str, Any]) -> dict[str, str | None]:
    images = item.get("images")
    if not isinstance(images, dict):
        images = {}
    poster = _first_image_url(images, POSTER_RATIOS)
    landscape = _first_image_url(images, LANDSCAPE_RATIOS)
    return {
        "poster": poster,
        "thumb": landscape,
        "landscape": landscape,
        "fanart": landscape,
    }


def genres_from_item(item: Mapping[str, Any]) -> tuple[str, ...]:
    names: list[str] = []

    def add(name: Any) -> None:
        if isinstance(name, str):
            cleaned = name.strip()
            if cleaned and cleaned not in names:
                names.append(cleaned)

    main_category = item.get("mainCategory")
    if isinstance(main_category, dict):
        add(main_category.get("name"))
    for key in ("categories", "genres"):
        block = item.get(key)
        if not isinstance(block, list):
            continue
        for entry in block:
            if isinstance(entry, dict):
                add(entry.get("name"))
            elif isinstance(entry, str):
                add(entry)
    return tuple(names)


def map_item(raw: Any) -> DirectoryItem | None:
    if not isinstance(raw, dict):
        LOGGER.warning("skipping malformed item")
        return None
    item_id = coerce_int(raw.get("id"))
    item_type = raw.get("type")
    if item_id is None:
        LOGGER.warning("skipping item without a stable id")
        return None
    if item_type not in TYPE_META:
        LOGGER.warning("skipping unknown item type %s", item_type)
        return None
    meta = TYPE_META[item_type]
    title = raw.get("title")
    plot = raw.get("lead")
    if not isinstance(plot, str) or not plot.strip():
        description = raw.get("description")
        plot = description if isinstance(description, str) else ""
    if not isinstance(title, str):
        title = ""
    season = raw.get("season") if isinstance(raw.get("season"), dict) else {}
    season_number = coerce_int(raw.get("seasonNumber")) or coerce_int(season.get("number"))
    episode_number = None
    if item_type == "SEASON":
        season_number = coerce_int(raw.get("number")) or season_number
    elif item_type == "EPISODE":
        episode_number = coerce_int(raw.get("number"))
    return DirectoryItem(
        id=item_id,
        type=str(item_type),
        title=title,
        plot=plot,
        year=coerce_int(raw.get("year")),
        duration=coerce_int(raw.get("duration")),
        genres=genres_from_item(raw),
        season_number=season_number,
        episode_number=episode_number,
        art=artwork_from_item(raw),
        content=meta["content"],
        media_type=meta["media_type"],
        is_playable=meta["is_playable"],
        is_folder=meta["is_folder"],
    )


def map_items(raw_items: Any) -> tuple[DirectoryItem, ...]:
    if not isinstance(raw_items, list):
        return ()
    mapped: list[DirectoryItem] = []
    for raw in raw_items:
        item = map_item(raw)
        if item is not None:
            mapped.append(item)
    return tuple(mapped)


def _envelope_items_and_meta(payload: Any) -> tuple[list[Any], dict[str, Any]]:
    if isinstance(payload, list):
        return payload, {}
    if not isinstance(payload, dict):
        return [], {}
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    merged_meta = dict(meta)
    for key in ("totalCount", "firstResult", "maxResults"):
        if key not in merged_meta and key in payload:
            merged_meta[key] = payload[key]
    return items, merged_meta


def _with_episode_full_title(raw: Any) -> Any:
    if not isinstance(raw, dict) or raw.get("type") != "EPISODE":
        return raw
    full_title = raw.get("fullTitle")
    if not isinstance(full_title, str):
        return raw
    cleaned = full_title.strip()
    if not cleaned:
        return raw
    updated = dict(raw)
    updated["title"] = cleaned
    return updated


def parse_search_page(
    payload: Any,
    first_result: int | None = None,
    page_size: int | None = None,
) -> SearchPage:
    raw_items, _meta = _envelope_items_and_meta(payload)
    resolved_first = 0 if first_result is None else first_result
    resolved_size = PAGE_SIZE if page_size is None else page_size
    prepared = [_with_episode_full_title(raw) for raw in raw_items[:resolved_size]]
    return SearchPage(
        items=map_items(prepared),
        first_result=resolved_first,
        page_size=resolved_size,
        has_next=len(raw_items) > resolved_size,
    )


def parse_catalog_page(
    payload: Any,
    first_result: int | None = None,
    page_size: int | None = None,
) -> CatalogPage:
    raw_items, meta = _envelope_items_and_meta(payload)
    items = map_items(raw_items)
    resolved_first = coerce_int(meta.get("firstResult"))
    if resolved_first is None:
        resolved_first = 0 if first_result is None else first_result
    resolved_size = coerce_int(meta.get("maxResults"))
    if resolved_size is None:
        resolved_size = PAGE_SIZE if page_size is None else page_size
    total_count = coerce_int(meta.get("totalCount"))
    return CatalogPage(
        items=items,
        first_result=resolved_first,
        page_size=resolved_size,
        total_count=total_count,
        has_next=has_next_page(resolved_first, len(items), total_count, resolved_size),
    )


def parse_item_list(payload: Any) -> tuple[DirectoryItem, ...]:
    if isinstance(payload, list):
        return map_items(payload)
    if isinstance(payload, dict):
        return parse_catalog_page(payload).items
    return ()


def map_section_element(raw: Any) -> DirectoryItem | None:
    if not isinstance(raw, dict):
        LOGGER.warning("skipping malformed section element")
        return None
    nested = raw.get("item")
    return map_item(nested if nested is not None else raw)


def parse_section(raw: Any) -> SectionView | None:
    if not isinstance(raw, dict):
        LOGGER.warning("skipping malformed section")
        return None
    section_id = coerce_int(raw.get("id"))
    if section_id is None:
        LOGGER.warning("skipping section without a stable id")
        return None
    title = raw.get("title")
    if not isinstance(title, str):
        title = ""
    elements = raw.get("elements")
    if not isinstance(elements, list):
        elements = raw.get("items") if isinstance(raw.get("items"), list) else []
    mapped: list[DirectoryItem] = []
    for element in elements:
        item = map_section_element(element)
        if item is not None:
            mapped.append(item)
    return SectionView(id=section_id, title=title, items=tuple(mapped))


def parse_sections(payload: Any) -> tuple[SectionView, ...]:
    if not isinstance(payload, list):
        LOGGER.warning("skipping malformed sections payload")
        return ()
    sections: list[SectionView] = []
    for raw in payload:
        section = parse_section(raw)
        if section is not None:
            sections.append(section)
    return tuple(sections)


def find_section(sections: Sequence[SectionView], section_id: Any) -> SectionView | None:
    wanted = coerce_int(section_id)
    if wanted is None:
        return None
    for section in sections:
        if section.id == wanted:
            return section
    return None


def _first_stream(sources: Mapping[str, Any], key: str) -> str | None:
    entries = sources.get(key)
    if entries is None:
        entries = sources.get(key.lower())
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        url = normalize_url(entry.get("src") or entry.get("url"))
        if url:
            return url
    return None


def parse_playlist(payload: Any) -> PlaylistView | None:
    if not isinstance(payload, dict):
        LOGGER.warning("skipping malformed playlist")
        return None
    sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    drm = payload.get("drm") if isinstance(payload.get("drm"), dict) else {}
    widevine = drm.get("WIDEVINE")
    if not isinstance(widevine, dict):
        widevine = drm.get("widevine") if isinstance(drm.get("widevine"), dict) else {}
    license_url = normalize_url(widevine.get("src") or widevine.get("licenseUrl"))
    subtitles: list[str] = []
    raw_subs = payload.get("subtitles")
    if isinstance(raw_subs, list):
        for sub in raw_subs:
            if not isinstance(sub, dict):
                continue
            url = normalize_url(sub.get("src") or sub.get("url"))
            if url:
                subtitles.append(url)
    return PlaylistView(
        dash_url=_first_stream(sources, "DASH"),
        hls_url=_first_stream(sources, "HLS"),
        widevine_license_url=license_url,
        has_drm=license_url is not None,
        subtitles=tuple(subtitles),
    )
