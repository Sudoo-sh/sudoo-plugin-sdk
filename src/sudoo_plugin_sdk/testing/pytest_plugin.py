"""pytest fixtures for plugin tests, loaded automatically when sudoo-plugin-sdk is installed.

sudoo_project    the plugin folder (the nearest folder above the tests with a manifest.json)
sudoo_manifest   its manifest, validated
fake_services    a FakeServices (instances, jobs, backups, events ... in memory)
sudoo_context    a PluginContext with the manifest's id, version, setting defaults and permissions
memory_storage   the context's MemoryStorage (when the manifest asks for storage)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sudoo_plugin_sdk.context import PluginContext
from sudoo_plugin_sdk.manifest import MANIFEST_NAME, Manifest, load_manifest
from sudoo_plugin_sdk.testing import FakeServices, MemoryStorage, make_context


def find_project(start: Path) -> Path | None:
    for folder in (start, *start.parents):
        if (folder / MANIFEST_NAME).is_file():
            return folder
    return None


@pytest.fixture
def sudoo_project(request: pytest.FixtureRequest) -> Path:
    project = find_project(Path(str(request.node.path)).parent)
    if project is None:
        pytest.skip("No manifest.json above this test.")
    return project


@pytest.fixture
def sudoo_manifest(sudoo_project: Path) -> Manifest:
    return load_manifest(sudoo_project)


@pytest.fixture
def fake_services() -> FakeServices:
    return FakeServices()


@pytest.fixture
def sudoo_context(sudoo_manifest: Manifest, fake_services: FakeServices, tmp_path: Path) -> PluginContext:
    return make_context(sudoo_manifest, services=fake_services, data_dir=tmp_path / "data")


@pytest.fixture
def memory_storage(sudoo_context: PluginContext) -> MemoryStorage:
    if not isinstance(sudoo_context.storage, MemoryStorage):
        pytest.skip("The manifest does not ask for storage.read or storage.write.")
    return sudoo_context.storage
