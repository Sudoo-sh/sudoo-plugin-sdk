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
    """Find the plugin folder: the nearest folder that holds a manifest.json.

    Args:
        start: The folder to start from.

    Returns:
        The folder, or None.
    """
    for folder in (start, *start.parents):
        if (folder / MANIFEST_NAME).is_file():
            return folder
    return None


@pytest.fixture
def sudoo_project(request: pytest.FixtureRequest) -> Path:
    """Fixture: the plugin folder. The test is skipped when there is no manifest.json above it.

    Args:
        request: The pytest request.

    Returns:
        The folder.
    """
    project = find_project(Path(str(request.node.path)).parent)
    if project is None:
        pytest.skip("No manifest.json above this test.")
    return project


@pytest.fixture
def sudoo_manifest(sudoo_project: Path) -> Manifest:
    """Fixture: the plugin's manifest.

    Args:
        sudoo_project: The plugin folder.

    Returns:
        The validated manifest.
    """
    return load_manifest(sudoo_project)


@pytest.fixture
def fake_services() -> FakeServices:
    """Fixture: a new fake panel.

    Returns:
        The services.
    """
    return FakeServices()


@pytest.fixture
def sudoo_context(sudoo_manifest: Manifest, fake_services: FakeServices, tmp_path: Path) -> PluginContext:
    """Fixture: a context for the plugin.

    Args:
        sudoo_manifest: The plugin's manifest.
        fake_services: The fake panel.
        tmp_path: A temporary folder; its "data" folder is the plugin's data folder.

    Returns:
        The context.
    """
    return make_context(sudoo_manifest, services=fake_services, data_dir=tmp_path / "data")


@pytest.fixture
def memory_storage(sudoo_context: PluginContext) -> MemoryStorage:
    """Fixture: the context's storage. The test is skipped when the manifest does not ask for storage.

    Args:
        sudoo_context: The context.

    Returns:
        The storage.
    """
    if not isinstance(sudoo_context.storage, MemoryStorage):
        pytest.skip("The manifest does not ask for storage.read or storage.write.")
    return sudoo_context.storage
