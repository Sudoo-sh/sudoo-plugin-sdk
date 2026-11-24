"""Shared fixtures: a factory for scaffolded plugin projects and a folder-copy helper."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sudoo_plugin_sdk.scaffold import scaffold

ProjectFactory = Callable[..., Path]


@pytest.fixture
def make_project(tmp_path: Path) -> ProjectFactory:
    """Fixture: a factory of scaffolded plugin projects in `tmp_path`, optionally with manifest changes."""
    counter = iter(range(1000))

    def factory(plugin_type: str = "theme", plugin_id: str | None = None, **manifest_changes: Any) -> Path:
        """Scaffold one project.

        Args:
            plugin_type: The plugin type.
            plugin_id: The plugin id; a numbered example id when None.
            **manifest_changes: Top-level manifest fields to overwrite after scaffolding.

        Returns:
            The project folder.
        """
        number = next(counter)
        identifier = plugin_id or f"com.example.p{number}-{plugin_type.replace('_', '-')}"
        target = scaffold(plugin_type, identifier, tmp_path / f"project{number}", author="Test Author")
        if manifest_changes:
            path = target / "manifest.json"
            data = json.loads(path.read_text())
            data.update(manifest_changes)
            path.write_text(json.dumps(data, indent=2))
        return target

    return factory


@pytest.fixture
def copy_tree() -> Callable[[Path, Path], Path]:
    """Fixture: a function that copies a folder tree."""

    def copy(source: Path, target: Path) -> Path:
        """Copy a folder tree.

        Args:
            source: The folder to copy.
            target: The new folder, which must not exist.

        Returns:
            The target.
        """
        shutil.copytree(source, target)
        return target

    return copy
