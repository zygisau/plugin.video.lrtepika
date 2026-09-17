# MIT License
"""ZIP packaging contract for plugin.video.lrtepika."""

from __future__ import annotations

import zipfile
from pathlib import Path

from tools.build import ADDON_ID, build_zip, validate_zip

ROOT = Path(__file__).resolve().parents[1]


def test_build_creates_single_wrapper_zip(tmp_path):
    artifact = build_zip(root=ROOT, dist_dir=tmp_path)
    assert artifact.name == "plugin.video.lrtepika-0.1.0.zip"
    validate_zip(artifact)

    with zipfile.ZipFile(artifact) as zf:
        names = zf.namelist()

    files = [name for name in names if not name.endswith("/")]
    wrappers = {name.split("/", 1)[0] for name in files}
    assert wrappers == {ADDON_ID}

    required = {
        f"{ADDON_ID}/addon.xml",
        f"{ADDON_ID}/main.py",
        f"{ADDON_ID}/LICENSE.txt",
        f"{ADDON_ID}/Readme.md",
        f"{ADDON_ID}/resources/lib/__init__.py",
        f"{ADDON_ID}/resources/lib/api.py",
        f"{ADDON_ID}/resources/lib/directory.py",
        f"{ADDON_ID}/resources/lib/plugin.py",
        f"{ADDON_ID}/resources/images/icon.png",
        f"{ADDON_ID}/resources/images/fanart.jpg",
    }
    assert required.issubset(names)

    joined = "\n".join(names)
    assert "plugin.video.example" not in joined
    assert "lrt_epika_api_client" not in joined
    assert "movies.json" not in joined
    assert "httpx" not in joined
    assert "/tests/" not in joined
    assert ".git/" not in joined
    assert ".venv" not in joined
    assert "__pycache__" not in joined
    assert "resources/images/icons/" not in joined
    assert "resources/images/screenshot-" not in joined

    with zipfile.ZipFile(artifact) as zf:
        addon_xml = zf.read(f"{ADDON_ID}/addon.xml").decode("utf-8")
    assert 'id="plugin.video.lrtepika"' in addon_xml
    assert 'version="0.1.0"' in addon_xml
    assert "plugin.video.example" not in addon_xml


def test_build_is_deterministic(tmp_path):
    first = build_zip(root=ROOT, dist_dir=tmp_path / "a")
    second = build_zip(root=ROOT, dist_dir=tmp_path / "b")
    assert first.read_bytes() == second.read_bytes()
