#!/usr/bin/env python3
# MIT License
"""Build a deterministic Kodi ZIP for plugin.video.lrtepika."""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

ADDON_ID = "plugin.video.lrtepika"
FIXED_DATE = (1980, 1, 1, 0, 0, 0)
FILE_ATTR = 0o644 << 16
DIR_ATTR = (0o755 << 16) | 0x10

REQUIRED_FILES = (
    "addon.xml",
    "main.py",
    "LICENSE.txt",
    "Readme.md",
    "resources/lib/__init__.py",
    "resources/lib/api.py",
    "resources/lib/directory.py",
    "resources/lib/history.py",
    "resources/lib/plugin.py",
)

OPTIONAL_LIB_FILES = (
    "resources/lib/api.py",
    "resources/lib/directory.py",
    "resources/lib/history.py",
)

REQUIRED_ASSETS = (
    "resources/images/icon.png",
    "resources/images/fanart.jpg",
)

EXCLUDED_NAME_PARTS = (
    "__pycache__",
    ".pyc",
    ".pyo",
    ".git",
    ".venv",
    "lrt_epika_api_client",
    "plugin.video.example",
)

EXCLUDED_ROOT_NAMES = {
    "tests",
    "tools",
    "dist",
    "build",
    ".venv",
    ".git",
    ".pytest_cache",
    ".claude",
    ".cursor",
    "__pycache__",
}

EXCLUDED_FILENAMES = {
    "movies.json",
    "lrt-epika-api.yaml",
    "requirements.txt",
    "makefile",
    "pytest.ini",
    "requirements-dev.txt",
    ".gitignore",
}

SAMPLE_ART_PREFIXES = (
    "resources/images/icons/",
    "resources/images/fanart/",
    "resources/images/screenshot-",
)

_ADDON_ID_RE = re.compile(r'<addon\b[^>]*\bid="([^"]+)"', re.DOTALL)
_ADDON_VERSION_RE = re.compile(r'<addon\b[^>]*\bversion="([^"]+)"', re.DOTALL)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_addon_metadata(addon_xml: Path) -> tuple[str, str]:
    text = addon_xml.read_text(encoding="utf-8")
    addon_id = _ADDON_ID_RE.search(text)
    version = _ADDON_VERSION_RE.search(text)
    if not addon_id or not version:
        raise SystemExit("addon.xml is missing id or version")
    return addon_id.group(1), version.group(1)


def should_include(relative: Path) -> bool:
    parts = relative.parts
    if not parts:
        return False
    if parts[0] in EXCLUDED_ROOT_NAMES:
        return False
    posix = relative.as_posix()
    if posix in EXCLUDED_FILENAMES:
        return False
    if any(token in posix for token in EXCLUDED_NAME_PARTS):
        return False
    if posix.endswith(".zip"):
        return False
    if any(posix.startswith(prefix) for prefix in SAMPLE_ART_PREFIXES):
        return False
    if parts[0] == "resources" and len(parts) >= 2 and parts[1] == "lib":
        if len(parts) != 3:
            return False
        allowed = {"__init__.py", "api.py", "directory.py", "plugin.py", "history.py"}
        return parts[2] in allowed
    return True


def iter_payload_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if should_include(relative):
            files.append(path)
    return files


def zip_info_for(arcname: str, is_dir: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(arcname, FIXED_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = DIR_ATTR if is_dir else FILE_ATTR
    return info


def build_zip(root: Path | None = None, dist_dir: Path | None = None) -> Path:
    root = root or repo_root()
    addon_xml = root / "addon.xml"
    addon_id, version = parse_addon_metadata(addon_xml)
    if addon_id != ADDON_ID:
        raise SystemExit(f"addon.xml id {addon_id!r} does not match {ADDON_ID!r}")

    payload = iter_payload_files(root)
    relative_names = {path.relative_to(root).as_posix() for path in payload}
    missing = [name for name in REQUIRED_FILES + REQUIRED_ASSETS if name not in relative_names]
    if missing:
        raise SystemExit("missing required add-on files: " + ", ".join(missing))

    dist_dir = dist_dir or (root / "dist")
    dist_dir.mkdir(parents=True, exist_ok=True)
    artifact = dist_dir / f"{addon_id}-{version}.zip"
    if artifact.exists():
        artifact.unlink()

    directories = {f"{addon_id}/"}
    for path in payload:
        parent = Path(addon_id) / path.relative_to(root)
        for ancestor in parent.parents:
            posix = ancestor.as_posix()
            if posix not in (".", addon_id):
                directories.add(posix.rstrip("/") + "/")
            elif posix == addon_id:
                directories.add(f"{addon_id}/")

    with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for directory in sorted(directories):
            zf.writestr(zip_info_for(directory, is_dir=True), b"")
        for path in payload:
            arcname = f"{addon_id}/{path.relative_to(root).as_posix()}"
            zf.writestr(zip_info_for(arcname), path.read_bytes())

    validate_zip(artifact)
    return artifact


def zip_namelist(archive: Path) -> list[str]:
    with zipfile.ZipFile(archive) as zf:
        return zf.namelist()


def validate_zip(archive: Path) -> None:
    names = zip_namelist(archive)
    if not names:
        raise SystemExit("ZIP is empty")

    wrappers = {name.split("/", 1)[0] for name in names if name}
    wrappers.discard("")
    if wrappers != {ADDON_ID}:
        raise SystemExit(f"ZIP must contain a single {ADDON_ID}/ wrapper, found {sorted(wrappers)}")

    required = {f"{ADDON_ID}/{name}" for name in REQUIRED_FILES + REQUIRED_ASSETS}
    missing = sorted(required.difference(names))
    if missing:
        raise SystemExit("ZIP missing required members: " + ", ".join(missing))

    joined = "\n".join(names)
    if "plugin.video.example" in joined:
        raise SystemExit("ZIP contains the old plugin.video.example id")
    if "lrt_epika_api_client" in joined:
        raise SystemExit("ZIP contains the generated OpenAPI client")
    if any(part in joined for part in ("/.git/", "__pycache__", ".venv", "/tests/")):
        raise SystemExit("ZIP contains excluded development files")
    if "movies.json" in joined or "lrt-epika-api.yaml" in joined:
        raise SystemExit("ZIP contains retired source artifacts")
    if "/resources/images/icons/" in joined or "/resources/images/fanart/" in joined:
        raise SystemExit("ZIP contains sample genre artwork")

    with zipfile.ZipFile(archive) as zf:
        bad = zf.testzip()
        if bad:
            raise SystemExit(f"ZIP failed integrity check: {bad}")
        addon_xml = zf.read(f"{ADDON_ID}/addon.xml").decode("utf-8")
        if f'id="{ADDON_ID}"' not in addon_xml:
            raise SystemExit("ZIP addon.xml id is not plugin.video.lrtepika")
        if "plugin.video.example" in addon_xml:
            raise SystemExit("ZIP addon.xml still references plugin.video.example")
        if "<license>MIT</license>" not in addon_xml:
            raise SystemExit("ZIP addon.xml is not MIT")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--dist", type=Path, default=None)
    args = parser.parse_args(argv)
    artifact = build_zip(root=args.root, dist_dir=args.dist)
    print(artifact)
    return 0


if __name__ == "__main__":
    sys.exit(main())
