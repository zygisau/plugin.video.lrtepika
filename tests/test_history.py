# MIT License
"""Search history persistence, normalization, and atomic replacement."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from resources.lib.history import add_history, load_history, normalize_term, save_history


def test_load_history_missing_file_is_empty(tmp_path):
    assert load_history(tmp_path / "search_history.json") == []


def test_load_history_corrupt_json_is_empty(tmp_path):
    path = tmp_path / "search_history.json"
    path.write_text("{not-json", encoding="utf-8")
    assert load_history(path) == []


def test_load_history_invalid_utf8_is_empty(tmp_path):
    path = tmp_path / "search_history.json"
    path.write_bytes(b"\xff\xfe not utf-8")
    assert load_history(path) == []


@pytest.mark.parametrize(
    "payload",
    [
        '{"items": ["lita"]}',
        '"lita"',
        "1",
        '["lita", 1]',
        '[{"term": "lita"}]',
    ],
)
def test_load_history_wrong_shape_is_empty(tmp_path, payload):
    path = tmp_path / "search_history.json"
    path.write_text(payload, encoding="utf-8")
    assert load_history(path) == []


def test_normalize_term_whitespace_and_nfkc():
    assert normalize_term("  Foo\tBar  ") == "Foo Bar"
    assert normalize_term("\uFB01sh") == "fish"
    assert normalize_term("\u2126") == "\u03a9"
    assert normalize_term(None) == ""
    assert normalize_term(12) == ""


def test_unicode_round_trip_and_trailing_newline(tmp_path):
    path = tmp_path / "search_history.json"
    add_history(path, "  šokis  ")
    text = path.read_text(encoding="utf-8")
    assert "šokis" in text
    assert "\\u" not in text
    assert text.endswith("\n")
    assert json.loads(text) == ["šokis"]
    assert load_history(path) == ["šokis"]


def test_casefold_and_nfkc_dedupe_keeps_newest_spelling(tmp_path):
    path = tmp_path / "search_history.json"
    add_history(path, "Café")
    add_history(path, "CAFÉ")
    add_history(path, "  café ")
    add_history(path, "\uFB01sh")
    add_history(path, "FISH")
    assert load_history(path) == ["FISH", "café"]


def test_newest_first_and_ten_entry_cap(tmp_path):
    path = tmp_path / "search_history.json"
    for index in range(11):
        add_history(path, f"term{index}")
    assert load_history(path) == [f"term{index}" for index in range(10, 0, -1)]


def test_empty_term_does_not_write(tmp_path):
    path = tmp_path / "search_history.json"
    assert add_history(path, "   ") == []
    assert not path.exists()


def test_save_history_replaces_atomically_in_same_directory(tmp_path, monkeypatch):
    path = tmp_path / "search_history.json"
    save_history(path, ["old"])
    recorded = {}
    real_mkstemp = __import__("tempfile").mkstemp

    def wrapped_mkstemp(*args, **kwargs):
        recorded["dir"] = kwargs.get("dir")
        recorded["result"] = real_mkstemp(*args, **kwargs)
        return recorded["result"]

    monkeypatch.setattr("tempfile.mkstemp", wrapped_mkstemp)
    save_history(path, ["new"])
    assert Path(recorded["dir"]) == tmp_path
    assert path.read_text(encoding="utf-8") == '["new"]\n'
    leftovers = [item for item in tmp_path.iterdir() if item != path]
    assert leftovers == []


def test_save_history_cleans_temp_file_on_failure(tmp_path, monkeypatch):
    path = tmp_path / "search_history.json"
    save_history(path, ["keep"])

    def boom(_src, _dst):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        save_history(path, ["lost"])
    assert json.loads(path.read_text(encoding="utf-8")) == ["keep"]
    leftovers = [item for item in tmp_path.iterdir() if item != path]
    assert leftovers == []


def test_empty_path_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_history("  ")
    with pytest.raises(ValueError):
        save_history("", ["lita"])
