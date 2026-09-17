# MIT License
"""Parse and resolve LRT Epika share URLs without fetching them."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from resources.lib.api import ApiError
from resources.lib.routes import (
    MAX_ID,
    episodes_plugin_url,
    play_plugin_url,
    serial_plugin_url,
)

MAX_URL_LENGTH = 1024
ALLOWED_HOST = "epika.lrt.lt"
ALLOWED_KINDS = ("VOD", "EPISODE", "SERIAL", "SEASON")
KIND_WIRE = {
    "VOD": "vod",
    "EPISODE": "episode",
    "SERIAL": "serial",
    "SEASON": "season",
}
_FINAL_ID_RE = re.compile(r",(\d+)$")


class SendReferenceError(Exception):
    status = 422
    code = "unsupported_url"


class UnsupportedUrlError(SendReferenceError):
    status = 422
    code = "unsupported_url"


class UnsupportedProductError(SendReferenceError):
    status = 422
    code = "unsupported_product"


class NotFoundError(SendReferenceError):
    status = 404
    code = "not_found"


class EpikaUnavailableError(SendReferenceError):
    status = 502
    code = "epika_unavailable"


@dataclass(frozen=True)
class ParsedReference:
    product_id: int
    parent_id: int | None


@dataclass(frozen=True)
class ResolvedReference:
    product_id: int
    kind: str
    title: str
    action: str
    plugin_url: str
    serial_id: int | None = None
    season_id: int | None = None

    @property
    def wire_kind(self) -> str:
        return KIND_WIRE[self.kind]


def parse_epika_url(url: Any) -> ParsedReference:
    if not isinstance(url, str) or not url:
        raise UnsupportedUrlError("unsupported_url")
    if len(url) > MAX_URL_LENGTH:
        raise UnsupportedUrlError("unsupported_url")
    if "\\" in url or "#" in url or "?" in url:
        raise UnsupportedUrlError("unsupported_url")
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        raise UnsupportedUrlError("unsupported_url")

    parts = urlsplit(url)
    if parts.scheme != "https":
        raise UnsupportedUrlError("unsupported_url")
    if parts.netloc != ALLOWED_HOST or parts.hostname != ALLOWED_HOST:
        raise UnsupportedUrlError("unsupported_url")
    if parts.username is not None or parts.password is not None or parts.port is not None:
        raise UnsupportedUrlError("unsupported_url")
    if parts.query or parts.fragment:
        raise UnsupportedUrlError("unsupported_url")

    path = parts.path
    if not path.startswith("/") or path.endswith("/"):
        raise UnsupportedUrlError("unsupported_url")
    segments = path.split("/")[1:]
    if not segments or any(not segment for segment in segments):
        raise UnsupportedUrlError("unsupported_url")

    product_id = _parse_segment_id(segments[-1], required=True)
    parent_id = None
    if len(segments) >= 2:
        parent_id = _parse_segment_id(segments[-2], required=False)
    return ParsedReference(product_id=product_id, parent_id=parent_id)


def resolve_epika_url(url: str, api) -> ResolvedReference:
    parsed = parse_epika_url(url)
    payload = _lookup_payload(api, parsed.product_id)
    return _reference_from_payload(parsed, payload)


def _parse_segment_id(segment: str, required: bool) -> int | None:
    match = _FINAL_ID_RE.search(segment)
    if match is None:
        if required:
            raise UnsupportedUrlError("unsupported_url")
        return None
    raw = match.group(1)
    if raw.startswith("0"):
        if required:
            raise UnsupportedUrlError("unsupported_url")
        return None
    value = int(raw)
    if value < 1 or value > MAX_ID:
        if required:
            raise UnsupportedUrlError("unsupported_url")
        return None
    return value


def _lookup_payload(api, product_id: int) -> dict[str, Any]:
    try:
        payload = api.get_product(product_id)
    except ApiError as exc:
        if exc.status != 404:
            raise EpikaUnavailableError("epika_unavailable") from exc
        try:
            payload = api.get_season_detail(product_id)
        except ApiError as season_exc:
            if season_exc.status == 404:
                raise NotFoundError("not_found") from season_exc
            raise EpikaUnavailableError("epika_unavailable") from season_exc
    except Exception as exc:
        raise EpikaUnavailableError("epika_unavailable") from exc

    if not isinstance(payload, dict):
        raise EpikaUnavailableError("epika_unavailable")
    return payload


def _reference_from_payload(parsed: ParsedReference, payload: dict[str, Any]) -> ResolvedReference:
    if payload.get("id") != parsed.product_id:
        raise UnsupportedProductError("unsupported_product")
    kind = _product_kind(payload)
    title = payload.get("title")
    title_text = title.strip() if isinstance(title, str) else ""
    serial_id = _nested_serial_id(payload, kind)
    if kind in ("EPISODE", "SEASON"):
        if serial_id is None or parsed.parent_id != serial_id:
            raise UnsupportedProductError("unsupported_product")

    web_url = payload.get("webUrl")
    if web_url is not None and web_url != "":
        if not isinstance(web_url, str):
            raise UnsupportedProductError("unsupported_product")
        try:
            canonical = parse_epika_url(web_url)
        except UnsupportedUrlError as exc:
            raise UnsupportedProductError("unsupported_product") from exc
        if canonical.product_id != parsed.product_id:
            raise UnsupportedProductError("unsupported_product")

    if kind in PLAYABLE:
        return ResolvedReference(
            product_id=parsed.product_id,
            kind=kind,
            title=title_text,
            action="play",
            plugin_url=play_plugin_url(parsed.product_id, kind),
            serial_id=serial_id,
        )
    if kind == "SERIAL":
        return ResolvedReference(
            product_id=parsed.product_id,
            kind=kind,
            title=title_text,
            action="browse",
            plugin_url=serial_plugin_url(parsed.product_id, title_text or None),
            serial_id=parsed.product_id,
        )
    return ResolvedReference(
        product_id=parsed.product_id,
        kind=kind,
        title=title_text,
        action="browse",
        plugin_url=episodes_plugin_url(serial_id, parsed.product_id, title_text or None),
        serial_id=serial_id,
        season_id=parsed.product_id,
    )


PLAYABLE = ("VOD", "EPISODE")


def _product_kind(payload: dict[str, Any]) -> str:
    primary = payload.get("type")
    fallback = payload.get("type_")
    if primary is not None and fallback is not None and primary != fallback:
        raise UnsupportedProductError("unsupported_product")
    kind = primary if primary is not None else fallback
    if kind not in ALLOWED_KINDS:
        raise UnsupportedProductError("unsupported_product")
    return kind


def _nested_serial_id(payload: dict[str, Any], kind: str) -> int | None:
    serial = None
    if kind == "EPISODE":
        season = payload.get("season")
        if not isinstance(season, dict):
            return None
        serial = season.get("serial")
    elif kind == "SEASON":
        serial = payload.get("serial")
    if not isinstance(serial, dict):
        return None
    value = serial.get("id")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 1 or value > MAX_ID:
        return None
    return value
