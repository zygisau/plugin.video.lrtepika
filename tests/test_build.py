# MIT License
"""ZIP packaging contract for plugin.video.lrtepika."""

from __future__ import annotations

import zipfile
from pathlib import Path

from tools.build import ADDON_ID, build_zip, validate_zip

ROOT = Path(__file__).resolve().parents[1]


def test_build_creates_single_wrapper_zip(tmp_path):
    artifact = build_zip(root=ROOT, dist_dir=tmp_path)
    assert artifact.name == "plugin.video.lrtepika-0.2.0.zip"
    validate_zip(artifact)

    with zipfile.ZipFile(artifact) as zf:
        names = zf.namelist()

    files = [name for name in names if not name.endswith("/")]
    wrappers = {name.split("/", 1)[0] for name in files}
    assert wrappers == {ADDON_ID}

    required = {
        f"{ADDON_ID}/addon.xml",
        f"{ADDON_ID}/main.py",
        f"{ADDON_ID}/service.py",
        f"{ADDON_ID}/LICENSE.txt",
        f"{ADDON_ID}/Readme.md",
        f"{ADDON_ID}/resources/lib/__init__.py",
        f"{ADDON_ID}/resources/lib/api.py",
        f"{ADDON_ID}/resources/lib/directory.py",
        f"{ADDON_ID}/resources/lib/history.py",
        f"{ADDON_ID}/resources/lib/plugin.py",
        f"{ADDON_ID}/resources/lib/routes.py",
        f"{ADDON_ID}/resources/lib/send_http.py",
        f"{ADDON_ID}/resources/lib/send_reference.py",
        f"{ADDON_ID}/resources/lib/send_service.py",
        f"{ADDON_ID}/resources/settings.xml",
        f"{ADDON_ID}/resources/language/resource.language.en_gb/strings.po",
        f"{ADDON_ID}/resources/language/resource.language.lt_lt/strings.po",
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
        settings_xml = zf.read(f"{ADDON_ID}/resources/settings.xml").decode("utf-8")
        readme = zf.read(f"{ADDON_ID}/Readme.md").decode("utf-8")
        english = zf.read(f"{ADDON_ID}/resources/language/resource.language.en_gb/strings.po").decode("utf-8")
        lithuanian = zf.read(f"{ADDON_ID}/resources/language/resource.language.lt_lt/strings.po").decode("utf-8")
    assert 'id="plugin.video.lrtepika"' in addon_xml
    assert 'version="0.2.0"' in addon_xml
    assert 'point="xbmc.service"' in addon_xml
    assert 'library="service.py"' in addon_xml
    assert "plugin.video.example" not in addon_xml
    assert "<default>false</default>" in settings_xml
    assert "127.0.0.1" in settings_xml
    assert "Bearer " not in settings_xml
    assert "REPLACE_WITH_RANDOM_TOKEN" in readme
    assert "msgctxt \"#32010\"" in english
    assert "Įjungti siuntimą į Kodi" in lithuanian


def test_build_is_deterministic(tmp_path):
    first = build_zip(root=ROOT, dist_dir=tmp_path / "a")
    second = build_zip(root=ROOT, dist_dir=tmp_path / "b")
    assert first.read_bytes() == second.read_bytes()
