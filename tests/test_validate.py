"""Tests of project validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sudoo_plugin_sdk.manifest import PLUGIN_TYPES
from sudoo_plugin_sdk.validate import validate
from tests.conftest import ProjectFactory


def _errors(project: Path) -> list[str]:
    """Validate a project.

    Args:
        project: The project folder.

    Returns:
        The errors.
    """
    return validate(project).errors


@pytest.mark.parametrize("plugin_type", PLUGIN_TYPES)
def test_every_scaffold_validates(make_project: ProjectFactory, plugin_type: str) -> None:
    """Test: every scaffold validates."""
    report = validate(make_project(plugin_type))
    assert report.errors == []


def test_a_theme_asks_for_no_permission(make_project: ProjectFactory) -> None:
    """Test: a theme asks for no permission."""
    errors = _errors(make_project("theme", permissions=["network.outbound"]))
    assert any("needs no permission" in e for e in errors)


def test_required_permissions_of_a_group(make_project: ProjectFactory) -> None:
    """Test: required permissions of a group."""
    errors = _errors(make_project("api", permissions=[]))
    assert any("network.inbound" in e for e in errors)


def test_type_needs_its_group(make_project: ProjectFactory) -> None:
    """Test: type needs its group."""
    project = make_project("notification")
    path = project / "manifest.json"
    data = json.loads(path.read_text())
    data["type"] = "mailer"
    path.write_text(json.dumps(data))
    assert any("sudoo.mailers" in e for e in _errors(project))


def test_unknown_group(make_project: ProjectFactory) -> None:
    """Test: unknown group."""
    project = make_project("theme")
    data = json.loads((project / "manifest.json").read_text())
    data["entry_points"]["sudoo.nonsense"] = {"x": "a.b:C"}
    (project / "manifest.json").write_text(json.dumps(data))
    errors = _errors(project)
    assert any("no entry-point group sudoo.nonsense" in e for e in errors)
    assert any("pyproject.toml differ" in e for e in errors)


def test_pyproject_version_must_match(make_project: ProjectFactory) -> None:
    """Test: pyproject version must match."""
    project = make_project("theme", version="0.2.0")
    assert any("pyproject.toml says version 0.1.0" in e for e in _errors(project))


def test_import_failures_and_missing_methods(make_project: ProjectFactory) -> None:
    """Test: import failures and missing methods."""
    project = make_project("mailer", plugin_id="com.example.broken-mailer")
    plugin = project / "src" / "example_broken_mailer" / "plugin.py"
    plugin.write_text(plugin.read_text().replace("    def send(", "    def deliver("))
    assert any("lacks send of Mailer" in e for e in _errors(project))
    plugin.write_text("raise RuntimeError('boom')\n")
    assert any("cannot be imported: RuntimeError: boom" in e for e in _errors(project))
    assert validate(project, import_code=False).errors == []


def test_theme_files_are_checked(make_project: ProjectFactory) -> None:
    """Test: theme files are checked."""
    project = make_project("theme", plugin_id="com.example.bad-theme")
    folder = project / "src" / "example_bad_theme"
    (folder / "tokens.css").write_text(":root { --brand: red; }")
    (folder / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><script/></svg>')
    errors = _errors(project)
    assert any("--brand is not one of the panel's tokens" in e for e in errors)
    assert any("<script>" in e for e in errors)


def test_static_scan_warns(make_project: ProjectFactory) -> None:
    """Test: static scan warns."""
    project = make_project("extension", plugin_id="com.example.shell-out")
    (project / "src" / "example_shell_out" / "run.py").write_text("import os\nos.system('ls')\n")
    report = validate(project)
    assert report.errors == []
    assert any("os.system()" in w for w in report.warnings)


def test_missing_manifest(tmp_path: Path) -> None:
    """Test: missing manifest."""
    assert validate(tmp_path).errors


def test_invalid_manifest_fields_are_named(make_project: ProjectFactory) -> None:
    """Test: invalid manifest fields are named."""
    errors = _errors(make_project("theme", version="one"))
    assert any(e.startswith("manifest.version:") for e in errors)
