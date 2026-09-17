# MIT License
"""Atomic UTF-8 search history for LRT Epika."""

from __future__ import annotations

import json
import os
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Iterable

HISTORY_FILENAME = "search_history.json"
HISTORY_LIMIT = 10


def normalize_term(value: Any) -> str:
    """Return a displayable search term, or an empty string if it is unusable."""
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _require_path(path: str | Path) -> Path:
    if isinstance(path, Path):
        text = str(path).strip()
    elif isinstance(path, str):
        text = path.strip()
    else:
        text = ""
    if not text:
        raise ValueError("history path is required")
    return Path(text)


def _unique_newest_first(terms: Iterable[Any], limit: int) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    cap = max(0, limit)
    for term in terms:
        normalized = normalize_term(term)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
        if len(unique) >= cap:
            break
    return unique


def load_history(path: str | Path, limit: int = HISTORY_LIMIT) -> list[str]:
    """Read newest-first history. Missing or corrupt files are treated as empty."""
    history_path = _require_path(path)
    try:
        raw = history_path.read_bytes()
    except FileNotFoundError:
        return []
    except OSError:
        return []
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return []
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        return []
    return _unique_newest_first(payload, limit)


def save_history(path: str | Path, terms: Iterable[Any], limit: int = HISTORY_LIMIT) -> None:
    """Replace history with a cleaned JSON list using an atomic same-directory write."""
    history_path = _require_path(path)
    payload = json.dumps(_unique_newest_first(terms, limit), ensure_ascii=False) + "\n"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".search_history.",
        suffix=".tmp",
        dir=str(history_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, history_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def add_history(path: str | Path, term: Any, limit: int = HISTORY_LIMIT) -> list[str]:
    """Insert a term at the front, preserving the newest spelling and cap."""
    history_path = _require_path(path)
    existing = load_history(history_path, limit=limit)
    normalized = normalize_term(term)
    if not normalized:
        return existing
    key = normalized.casefold()
    merged = [normalized] + [item for item in existing if item.casefold() != key]
    save_history(history_path, merged, limit=limit)
    return merged[: max(0, limit)]
