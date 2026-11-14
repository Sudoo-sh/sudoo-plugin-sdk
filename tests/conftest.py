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
    """A scaffolded plugin project in tmp_path, optionally with manifest changes."""
    counter = iter(range(1000))

    def factory(plugin_type: str = "theme", plugin_id: str | None = None, **manifest_changes: Any) -> Path:
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
    def copy(source: Path, target: Path) -> Path:
        shutil.copytree(source, target)
        return target

    return copy
