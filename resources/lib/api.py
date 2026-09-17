# MIT License
"""Thin requests client for the public LRT Epika API."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import requests

DEFAULT_BASE_URL = "https://epika.lrt.lt/api"
DEFAULT_LANG = "LIT"
DEFAULT_PLATFORM = "BROWSER"
DEFAULT_TIMEOUT = 10
DEFAULT_PAGE_SIZE = 30
TENANT_UID = "Lh8t"
SEARCH_TYPES = ("VOD", "SERIAL", "EPISODE")
SECTION_NAMES = ("main", "filmai", "serialai")
PLAYLIST_VIDEO_TYPES = ("MOVIE", "EPISODE")


class ApiError(Exception):
    """Safe API failure. Messages never include cookies, licenses, or stream URLs."""

    def __init__(self, operation: str, message: str, status: int | None = None):
        self.operation = operation
        self.status = status
        safe_message = message
        super().__init__(f"{operation}: {safe_message}")


def _as_int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ApiError("validate", f"invalid {name}") from exc


class EpikaApi:
    """HTTP wrapper. This module is the only place that performs network I/O."""

    def __init__(
        self,
        session: requests.Session | None = None,
        base_url: str = DEFAULT_BASE_URL,
        lang: str = DEFAULT_LANG,
        platform: str = DEFAULT_PLATFORM,
        timeout: float = DEFAULT_TIMEOUT,
        tenant_uid: str = TENANT_UID,
    ):
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self.lang = lang
        self.platform = platform
        self.timeout = timeout
        self.tenant_uid = tenant_uid

    def _params(self, extra: Sequence[tuple[str, Any]] | None = None) -> list[tuple[str, Any]]:
        params: list[tuple[str, Any]] = [
            ("lang", self.lang),
            ("platform", self.platform),
        ]
        if extra:
            params.extend(extra)
        return params

    def _get(
        self,
        operation: str,
        path: str,
        params: Sequence[tuple[str, Any]] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.Timeout as exc:
            raise ApiError(operation, "timed out") from exc
        except requests.RequestException as exc:
            raise ApiError(operation, "request failed") from exc

        status = getattr(response, "status_code", None)
        if not isinstance(status, int) or status < 200 or status >= 300:
            raise ApiError(operation, f"HTTP {status}", status=status)

        try:
            return response.json()
        except ValueError as exc:
            raise ApiError(operation, "invalid JSON") from exc

    def get_sections(self, section_name: str, elements_limit: int = DEFAULT_PAGE_SIZE) -> Any:
        if section_name not in SECTION_NAMES:
            raise ApiError("get_sections", "unsupported section")
        return self._get(
            "get_sections",
            f"/products/sections/{section_name}",
            self._params(
                [
                    ("elementsLimit", _as_int(elements_limit, "elements_limit")),
                ]
            ),
        )

    def get_categories(self, main_category_id: int) -> Any:
        return self._get(
            "get_categories",
            "/items/categories",
            self._params([("mainCategoryId", _as_int(main_category_id, "main_category_id"))]),
        )

    def get_catalog(
        self,
        main_category_ids: Iterable[int],
        category_ids: Iterable[int] | None = None,
        first_result: int = 0,
        max_results: int = DEFAULT_PAGE_SIZE,
    ) -> Any:
        extra: list[tuple[str, Any]] = [
            ("firstResult", _as_int(first_result, "first_result")),
            ("maxResults", _as_int(max_results, "max_results")),
        ]
        for category_id in main_category_ids:
            extra.append(("mainCategoryId[]", _as_int(category_id, "main_category_id")))
        for category_id in category_ids or ():
            extra.append(("categoryId[]", _as_int(category_id, "category_id")))
        return self._get("get_catalog", "/products/vods", self._params(extra))

    def search(
        self,
        item_type: str,
        keyword: str,
        first_result: int = 0,
        max_results: int = DEFAULT_PAGE_SIZE,
    ) -> Any:
        if item_type not in SEARCH_TYPES:
            raise ApiError("search", "unsupported item type")
        extra = [
            ("keyword", keyword),
            ("firstResult", _as_int(first_result, "first_result")),
            ("maxResults", _as_int(max_results, "max_results")),
        ]
        return self._get(
            "search",
            f"/products/vods/search/{item_type}",
            self._params(extra),
        )

    def get_product(self, product_id: int) -> Any:
        pid = _as_int(product_id, "product_id")
        return self._get("get_product", f"/products/vods/{pid}", self._params())

    def get_serial_seasons(self, serial_id: int) -> Any:
        sid = _as_int(serial_id, "serial_id")
        return self._get(
            "get_serial_seasons",
            f"/products/vods/serials/{sid}/seasons",
            self._params(),
        )

    def get_season_episodes(self, serial_id: int, season_id: int) -> Any:
        sid = _as_int(serial_id, "serial_id")
        season = _as_int(season_id, "season_id")
        return self._get(
            "get_season_episodes",
            f"/products/vods/serials/{sid}/seasons/{season}/episodes",
            self._params(),
        )

    def get_playlist(self, product_id: int, video_type: str) -> Any:
        if video_type not in PLAYLIST_VIDEO_TYPES:
            raise ApiError("get_playlist", "unsupported video type")
        pid = _as_int(product_id, "product_id")
        extra = [
            ("videoType", video_type),
            ("platform", self.platform),
            ("tenantUid", self.tenant_uid),
        ]
        # Playlist is documented without lang; still send platform via extra only.
        return self._get(
            "get_playlist",
            f"/products/{pid}/videos/playlist",
            extra,
        )
