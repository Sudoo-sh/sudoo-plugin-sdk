"""Tests of the fake panel in `sudoo_plugin_sdk.testing`."""

from __future__ import annotations

from pathlib import Path

import pytest

from sudoo_plugin_sdk.context import Caller, PluginSettings, ServiceError, Services
from sudoo_plugin_sdk.manifest import Manifest
from sudoo_plugin_sdk.testing import FakeServices, MemorySecrets, MemoryStorage, Outbox, make_context, person
from tests.test_manifest import EXAMPLE


def test_context_from_a_manifest(tmp_path: Path) -> None:
    """Test: context from a manifest."""
    manifest = Manifest.model_validate(EXAMPLE)
    context = make_context(manifest, data_dir=tmp_path / "data", settings={"smtp_host": "mail.example.test"})
    assert context.plugin_id == "com.sudoo.smtp" and context.version == "1.0.0"
    assert context.settings.string("smtp_host") == "mail.example.test"
    assert context.settings.integer("smtp_port") == 587
    assert context.permissions == frozenset({"network.outbound"})
    assert context.storage is None and context.secrets is None and context.mail is None
    assert (tmp_path / "data").is_dir()
    assert isinstance(context.services, Services)


def test_context_capabilities_follow_permissions(tmp_path: Path) -> None:
    """Test: context capabilities follow permissions."""
    context = make_context(
        "com.example.x", permissions={"storage.read", "storage.write", "secrets", "mail.send"}, data_dir=tmp_path
    )
    assert isinstance(context.storage, MemoryStorage)
    assert isinstance(context.secrets, MemorySecrets)
    assert isinstance(context.mail, Outbox)
    context.require("secrets")
    with pytest.raises(PermissionError):
        context.require("docker")


def test_make_context_needs_a_folder() -> None:
    """Test: make context needs a folder."""
    with pytest.raises(ValueError, match="data_dir"):
        make_context("com.example.x")


def test_services_check_permissions_and_record(tmp_path: Path) -> None:
    """Test: services check permissions and record."""
    services = FakeServices()
    services.instances.add("sales-main")
    viewer = person("instances.view")
    assert [i["name"] for i in services.instances.list(viewer)] == ["sales-main"]
    with pytest.raises(ServiceError) as refused:
        services.instances.create(viewer, {"name": "demo"})
    assert refused.value.status == 403
    with pytest.raises(ServiceError) as missing:
        services.instances.get(viewer, "nope")
    assert missing.value.status == 404
    assert [(c.service, c.method) for c in services.calls] == [
        ("instances", "list"),
        ("instances", "create"),
        ("instances", "get"),
    ]


def test_plugin_caller_gets_what_its_permissions_allow(tmp_path: Path) -> None:
    """Test: plugin caller gets what its permissions allow."""
    services = FakeServices()
    services.instances.add("sales-main")
    reader = make_context("com.example.r", permissions={"instances.read"}, services=services, data_dir=tmp_path)
    assert reader.caller.name == "plugin:com.example.r" and reader.caller.via == "plugin"
    assert services.instances.get(reader.caller, "sales-main")["name"] == "sales-main"
    with pytest.raises(ServiceError):
        services.instances.run(reader.caller, "sales-main", "restart")
    writer = make_context("com.example.w", permissions={"instances.write"}, services=services, data_dir=tmp_path)
    job = services.instances.run(writer.caller, "sales-main", "backup")
    assert services.jobs.wait(writer.caller, job["id"])["status"] == "success"


def test_create_delete_and_events(tmp_path: Path) -> None:
    """Test: create delete and events."""
    services = FakeServices()
    seen: list[str] = []
    stop = services.events.subscribe(["instance.created", "instance.deleted"], lambda e: seen.append(e["kind"]))
    admin = person("instances.view", "instances.create", "instances.delete")
    services.instances.create(admin, {"name": "demo", "branch": "feature/pos"})
    with pytest.raises(ServiceError):
        services.instances.delete(admin, "demo", confirm="wrong")
    services.instances.delete(admin, "demo", confirm="demo")
    stop()
    services.events.emit("instance.created", {"name": "later"})
    assert seen == ["instance.created", "instance.deleted"]


def test_backups_listing_rules() -> None:
    """Test: backups listing rules."""
    services = FakeServices()
    services.backups.add("a.zip", "sales-main")
    services.backups.add("b.zip", "other", version="18.0")
    viewer = person("instances.view")
    assert len(services.backups.list(viewer, instance="sales-main")) == 1
    with pytest.raises(ServiceError):
        services.backups.list(viewer)
    assert len(services.backups.list(person("backups.manage"))) == 2
    assert services.backups.compatible(viewer, "b.zip", "18.0")


def test_storage_change_is_atomic_style() -> None:
    """Test: storage change is atomic style."""
    storage = MemoryStorage()
    storage.put("tokens", "a", {"n": 1})
    storage.change("tokens", "a", lambda d: {"n": (d or {}).get("n", 0) + 1})
    assert storage.get("tokens", "a") == {"n": 2}
    storage.change("tokens", "a", lambda d: None)
    assert storage.get("tokens", "a") is None
    assert storage.delete("tokens", "a") is False


def test_settings_types() -> None:
    """Test: settings types."""
    settings = PluginSettings({"port": 587, "on": True, "ratio": 0.5, "name": None})
    assert settings.integer("port") == 587 and settings.boolean("on") and settings.number("ratio") == 0.5
    assert settings.string("name", "x") == "x"
    assert "587" not in repr(settings)
    with pytest.raises(ValueError):
        settings.integer("on")
    with pytest.raises(ValueError):
        settings.boolean("port")


def test_caller() -> None:
    """Test: caller."""
    caller = Caller("api:ci", frozenset({"instances.view"}), via="token", token_id="t1")
    assert caller.can("instances.view") and not caller.can("instances.delete")
