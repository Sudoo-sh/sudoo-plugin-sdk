from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from sudoo_plugin_sdk.manifest import load_manifest
from sudoo_plugin_sdk.package import FIXED_TIME, PackError, collect, matches, pack, read_manifest
from tests.conftest import ProjectFactory


def _entries(path: Path) -> list[zipfile.ZipInfo]:
    with zipfile.ZipFile(path) as archive:
        return archive.infolist()


def test_pack_is_deterministic(make_project: ProjectFactory, tmp_path: Path) -> None:
    project = make_project("theme", "com.example.same-theme")
    manifest = load_manifest(project)
    first = pack(project, manifest, tmp_path / "a")
    # different modification times, an extra cache file, a different creation order: same bytes
    for path in project.rglob("*"):
        if path.is_file():
            os.utime(path, (1_700_000_000, 1_700_000_000))
    cache = project / "src" / "example_same_theme" / "__pycache__"
    cache.mkdir()
    (cache / "plugin.cpython-314.pyc").write_bytes(b"\x00compiled")
    second = pack(project, manifest, tmp_path / "b")
    assert first.sha256 == second.sha256
    assert first.path.read_bytes() == second.path.read_bytes()
    assert first.path.name == "com.example.same-theme-0.1.0.sudoo"


def test_entries_are_sorted_fixed_and_plain(make_project: ProjectFactory, tmp_path: Path) -> None:
    project = make_project("theme", "com.example.plain-theme")
    packed = pack(project, load_manifest(project), tmp_path)
    entries = _entries(packed.path)
    names = [e.filename for e in entries]
    assert names == sorted(names)
    assert names[0] == "CHANGELOG.md" and "manifest.json" in names
    assert "src/example_plain_theme/tokens.css" in names and "src/example_plain_theme/logo.svg" in names
    assert not any(n.startswith("tests/") or n.startswith(".") or n.endswith("/") for n in names)
    for entry in entries:
        assert entry.date_time == FIXED_TIME
        assert entry.external_attr >> 16 == 0o100644
        assert entry.compress_type == zipfile.ZIP_STORED
        assert entry.extra == b""
    assert read_manifest(packed.path).id == "com.example.plain-theme"


def test_compressed_packages_are_deterministic_too(make_project: ProjectFactory, tmp_path: Path) -> None:
    project = make_project("theme")
    manifest = load_manifest(project)
    one = pack(project, manifest, tmp_path / "1", compress=True)
    two = pack(project, manifest, tmp_path / "2", compress=True)
    assert one.sha256 == two.sha256
    assert all(e.compress_type == zipfile.ZIP_DEFLATED for e in _entries(one.path))


@pytest.mark.parametrize("name", [".env", "deploy.pem", "id_ed25519", "server.key"])
def test_forbidden_files_stop_the_build(make_project: ProjectFactory, name: str, tmp_path: Path) -> None:
    project = make_project("theme")
    (project / "src" / name).write_text("secret")
    with pytest.raises(PackError, match="must not be in a package"):
        pack(project, load_manifest(project), tmp_path)


def test_links_are_refused(make_project: ProjectFactory, tmp_path: Path) -> None:
    project = make_project("theme")
    (project / "assets").mkdir()
    (project / "assets" / "link").symlink_to(project / "README.md")
    with pytest.raises(PackError, match="symbolic link"):
        pack(project, load_manifest(project), tmp_path)


def test_compiled_files_are_a_warning(make_project: ProjectFactory) -> None:
    project = make_project("theme")
    (project / "src" / "native.so").write_bytes(b"\x7fELF")
    contents = collect(project, load_manifest(project))
    assert not contents.errors
    assert any("native.so" in w for w in contents.warnings)


def test_missing_declared_files(make_project: ProjectFactory, tmp_path: Path) -> None:
    project = make_project("theme", icon="icon.svg")
    with pytest.raises(PackError, match=r"icon\.svg does not exist"):
        pack(project, load_manifest(project), tmp_path)


def test_hub_pattern_rule() -> None:
    assert matches("src/.git/config", (".git/*",))
    assert matches("a/b/.env.local", (".env.*",))
    assert not matches("src/environment.py", (".env",))


def test_read_manifest_errors(tmp_path: Path) -> None:
    path = tmp_path / "x.sudoo"
    path.write_bytes(b"not a zip")
    with pytest.raises(ValueError, match=r"not a \.sudoo package"):
        read_manifest(path)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("README.md", "x")
    with pytest.raises(ValueError, match=r"no manifest\.json"):
        read_manifest(path)
