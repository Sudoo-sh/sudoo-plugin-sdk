"""A fake panel for plugin tests: services, settings, storage, secrets and mail in memory, no panel needed.

    from sudoo_plugin_sdk.testing import make_context

    def test_notifies(tmp_path):
        context = make_context("com.example.slack", settings={"webhook_url": "https://hooks.example/x"},
                               permissions={"network.outbound"}, data_dir=tmp_path)
        channel = Slack(context)
        ...

With pytest, the fixtures `sudoo_manifest`, `sudoo_context`, `fake_services` and `memory_storage` are available
without importing anything (sudoo_plugin_sdk.testing.pytest_plugin).
"""

from __future__ import annotations

import builtins
import copy
import itertools
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sudoo_plugin_sdk.context import (
    Caller,
    Document,
    Event,
    PluginContext,
    PluginSettings,
    Resource,
    RouteInfo,
    ServiceError,
    Unsubscribe,
)
from sudoo_plugin_sdk.manifest import Manifest

__all__ = [
    "FakeServices",
    "MemorySecrets",
    "MemoryStorage",
    "Outbox",
    "make_context",
    "person",
    "settings_from_manifest",
]


def person(*permissions: str, name: str = "sam") -> Caller:
    """A Caller as the core builds it for someone signed in, with these panel permissions."""
    return Caller(name=name, permissions=frozenset(permissions), via="session")


def _need(caller: Caller, permission: str) -> None:
    if not caller.can(permission):
        raise ServiceError(403, "Not allowed", f"{caller.name} lacks {permission}.")


@dataclass
class Call:
    service: str
    method: str
    caller: str
    arguments: dict[str, Any]


class _Recorder:
    def __init__(self, calls: list[Call], service: str) -> None:
        self._calls = calls
        self._service = service

    def _record(self, method: str, caller: Caller, **arguments: Any) -> None:
        self._calls.append(Call(self._service, method, caller.name, arguments))


class FakeInstances(_Recorder):
    def __init__(self, calls: list[Call], jobs: FakeJobs, events: FakeEvents) -> None:
        super().__init__(calls, "instances")
        self.items: dict[str, Resource] = {}
        self.logs_by_instance: dict[str, list[str]] = {}
        self._jobs = jobs
        self._events = events

    def add(self, name: str, **fields: Any) -> Resource:
        """Put an instance in the fake panel: add("sales-main", branch="main", version="19.0")."""
        resource: Resource = {
            "name": name,
            "status": "running",
            "branch": "main",
            "version": "19.0",
            "edition": "community",
            "url": f"https://{name}.example.test",
        } | fields
        self.items[name] = resource
        return resource

    def _find(self, name: str) -> Resource:
        if name not in self.items:
            raise ServiceError(404, "Not found", f"No instance {name}.")
        return self.items[name]

    def list(self, caller: Caller, limit: int = 50, offset: int = 0) -> list[Resource]:
        self._record("list", caller, limit=limit, offset=offset)
        _need(caller, "instances.view")
        return [copy.deepcopy(r) for r in list(self.items.values())[offset : offset + limit]]

    def get(self, caller: Caller, name: str) -> Resource:
        self._record("get", caller, name=name)
        _need(caller, "instances.view")
        return copy.deepcopy(self._find(name))

    def plan(
        self, caller: Caller, repo: str, branch: str, name: str | None = None, from_backup: str | None = None
    ) -> Resource:
        self._record("plan", caller, repo=repo, branch=branch, name=name, from_backup=from_backup)
        _need(caller, "instances.create")
        chosen = name or branch.replace("/", "-").lower()
        return {"name": chosen, "database": chosen.replace("-", "_"), "quota_ok": True, "from_backup": from_backup}

    def quota(self, caller: Caller) -> Resource:
        self._record("quota", caller)
        _need(caller, "instances.view")
        return {"used": len(self.items), "limit": 0}

    def create(self, caller: Caller, fields: Mapping[str, Any]) -> Resource:
        self._record("create", caller, fields=dict(fields))
        _need(caller, "instances.create")
        name = str(fields.get("name") or str(fields.get("branch", "instance")).replace("/", "-"))
        if name in self.items:
            raise ServiceError(409, "Already exists", f"An instance {name} exists.")
        self.add(name, **{k: v for k, v in fields.items() if k != "name"}, status="creating")
        self._events.emit("instance.created", self.items[name])
        return self._jobs.start("create", name)

    def change(self, caller: Caller, name: str, fields: Mapping[str, Any]) -> Resource:
        self._record("change", caller, name=name, fields=dict(fields))
        _need(caller, "instances.update")
        self._find(name).update(fields)
        return copy.deepcopy(self.items[name])

    def run(self, caller: Caller, name: str, action: str, fields: Mapping[str, Any] | None = None) -> Resource:
        self._record("run", caller, name=name, action=action, fields=dict(fields or {}))
        permission = {"backup": "instances.operate", "pause": "instances.operate", "restore": "instances.restore"}
        _need(caller, permission.get(action, "instances.update"))
        self._find(name)
        return self._jobs.start(action, name)

    def delete(self, caller: Caller, name: str, confirm: str) -> Resource:
        self._record("delete", caller, name=name, confirm=confirm)
        _need(caller, "instances.delete")
        self._find(name)
        if confirm != name:
            raise ServiceError(422, "Not confirmed", "Type the instance's name to delete it.")
        job = self._jobs.start("delete", name)
        del self.items[name]
        self._events.emit("instance.deleted", {"name": name})
        return job

    def credentials(self, caller: Caller, name: str) -> Resource:
        self._record("credentials", caller, name=name)
        _need(caller, "instances.credentials")
        self._find(name)
        return {"login": "admin", "password": "test-password"}

    def logs(self, caller: Caller, name: str, lines: int = 200) -> builtins.list[str]:
        self._record("logs", caller, name=name, lines=lines)
        _need(caller, "instances.logs")
        self._find(name)
        return self.logs_by_instance.get(name, [])[-lines:]


class FakeJobs(_Recorder):
    def __init__(self, calls: list[Call]) -> None:
        super().__init__(calls, "jobs")
        self.items: dict[str, Resource] = {}
        self._ids = itertools.count(1)

    def start(self, kind: str, instance: str, status: str = "success") -> Resource:
        """A job the fake panel ran (finished at once, with `status`)."""
        job_id = f"job{next(self._ids):04d}"
        self.items[job_id] = {"id": job_id, "kind": kind, "instance": instance, "status": status, "log": ""}
        return copy.deepcopy(self.items[job_id])

    def _find(self, job_id: str) -> Resource:
        if job_id not in self.items:
            raise ServiceError(404, "Not found", f"No job {job_id}.")
        return self.items[job_id]

    def list(self, caller: Caller, instance: str | None = None, limit: int = 50, offset: int = 0) -> list[Resource]:
        self._record("list", caller, instance=instance, limit=limit, offset=offset)
        _need(caller, "instances.view")
        rows = [j for j in self.items.values() if instance is None or j["instance"] == instance]
        return [copy.deepcopy(j) for j in rows[offset : offset + limit]]

    def get(self, caller: Caller, job_id: str, include_log: bool = False) -> Resource:
        self._record("get", caller, job_id=job_id, include_log=include_log)
        _need(caller, "instances.view")
        job = copy.deepcopy(self._find(job_id))
        if not include_log:
            job.pop("log", None)
        return job

    def log(self, caller: Caller, job_id: str, offset: int = 0) -> Resource:
        self._record("log", caller, job_id=job_id, offset=offset)
        _need(caller, "instances.logs")
        text = str(self._find(job_id).get("log", ""))
        return {"text": text[offset:], "offset": len(text)}

    def wait(self, caller: Caller, job_id: str, timeout: float = 60.0) -> Resource:
        self._record("wait", caller, job_id=job_id, timeout=timeout)
        _need(caller, "instances.view")
        return copy.deepcopy(self._find(job_id))


class FakeBackups(_Recorder):
    def __init__(self, calls: list[Call]) -> None:
        super().__init__(calls, "backups")
        self.items: list[Resource] = []

    def add(self, file: str, instance: str, version: str = "19.0", **fields: Any) -> Resource:
        resource: Resource = {"file": file, "instance": instance, "version": version, "size": 0} | fields
        self.items.append(resource)
        return resource

    def list(self, caller: Caller, instance: str | None = None, version: str | None = None) -> list[Resource]:
        self._record("list", caller, instance=instance, version=version)
        if not caller.can("backups.manage"):
            _need(caller, "instances.view")
            if instance is None:
                raise ServiceError(403, "Not allowed", "Name an instance to see its backups.")
        return [
            copy.deepcopy(b)
            for b in self.items
            if (instance is None or b["instance"] == instance) and (version is None or b["version"] == version)
        ]

    def compatible(self, caller: Caller, file: str, version: str) -> bool:
        self._record("compatible", caller, file=file, version=version)
        _need(caller, "instances.view")
        return any(b["file"] == file and b["version"] == version for b in self.items)

    def delete(self, caller: Caller, file: str) -> None:
        self._record("delete", caller, file=file)
        _need(caller, "backups.manage")
        self.items = [b for b in self.items if b["file"] != file]


class FakeVersions(_Recorder):
    def __init__(self, calls: list[Call]) -> None:
        super().__init__(calls, "versions")
        self.items: list[Resource] = [
            {"version": "17.0", "enterprise": False},
            {"version": "18.0", "enterprise": False},
            {"version": "19.0", "enterprise": False},
        ]

    def list(self, caller: Caller) -> list[Resource]:
        self._record("list", caller)
        return copy.deepcopy(self.items)


class FakeDocs(_Recorder):
    def __init__(self, calls: list[Call]) -> None:
        super().__init__(calls, "docs")
        self.pages: dict[str, str] = {}

    def list(self, caller: Caller) -> list[Resource]:
        self._record("list", caller)
        return [{"path": path} for path in sorted(self.pages)]

    def get(self, caller: Caller, path: str) -> Resource:
        self._record("get", caller, path=path)
        if path not in self.pages:
            raise ServiceError(404, "Not found", f"No page {path}.")
        return {"path": path, "text": self.pages[path]}


class FakeServer(_Recorder):
    def __init__(self, calls: list[Call]) -> None:
        super().__init__(calls, "server")
        self.values: Resource = {"cpu_percent": 6.0, "memory_percent": 41.0, "disk_percent": 37.0}

    def figures(self, caller: Caller) -> Resource:
        self._record("figures", caller)
        _need(caller, "instances.view")
        return copy.deepcopy(self.values)


class FakeEvents:
    def __init__(self) -> None:
        self._subscribers: list[tuple[frozenset[str], Callable[[Event], None]]] = []
        self.sent: list[Event] = []

    def subscribe(self, kinds: list[str], callback: Callable[[Event], None]) -> Unsubscribe:
        entry = (frozenset(kinds), callback)
        self._subscribers.append(entry)

        def unsubscribe() -> None:
            if entry in self._subscribers:
                self._subscribers.remove(entry)

        return unsubscribe

    def emit(self, kind: str, data: Mapping[str, Any]) -> None:
        """Send an event to the subscribers, as the panel would."""
        event: Event = {"kind": kind, "data": copy.deepcopy(dict(data))}
        self.sent.append(event)
        for kinds, callback in list(self._subscribers):
            if not kinds or kind in kinds:
                callback(event)


class FakeRoutes:
    def __init__(self) -> None:
        self.items: list[RouteInfo] = [
            RouteInfo("GET", "/api/v1/instances", "instances.view", "List instances"),
            RouteInfo("POST", "/api/v1/instances", "instances.create", "Create an instance"),
        ]

    def list(self) -> list[RouteInfo]:
        return list(self.items)


class FakeServices:
    """`context.services` of a fake panel. Every call is recorded in `calls`; permissions are checked like the
    panel does (a ServiceError 403 when the caller lacks one)."""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self._events = FakeEvents()
        self._jobs = FakeJobs(self.calls)
        self._instances = FakeInstances(self.calls, self._jobs, self._events)
        self._backups = FakeBackups(self.calls)
        self._versions = FakeVersions(self.calls)
        self._docs = FakeDocs(self.calls)
        self._server = FakeServer(self.calls)
        self._routes = FakeRoutes()

    @property
    def instances(self) -> FakeInstances:
        return self._instances

    @property
    def jobs(self) -> FakeJobs:
        return self._jobs

    @property
    def backups(self) -> FakeBackups:
        return self._backups

    @property
    def versions(self) -> FakeVersions:
        return self._versions

    @property
    def docs(self) -> FakeDocs:
        return self._docs

    @property
    def server(self) -> FakeServer:
        return self._server

    @property
    def events(self) -> FakeEvents:
        return self._events

    @property
    def routes(self) -> FakeRoutes:
        return self._routes


class MemoryStorage:
    """The plugin's own records, in memory."""

    def __init__(self) -> None:
        self.collections: dict[str, dict[str, Document]] = {}

    def get(self, collection: str, key: str) -> Document | None:
        found = self.collections.get(collection, {}).get(key)
        return copy.deepcopy(found)

    def all(self, collection: str) -> dict[str, Document]:
        return copy.deepcopy(self.collections.get(collection, {}))

    def put(self, collection: str, key: str, document: Document) -> None:
        self.collections.setdefault(collection, {})[key] = copy.deepcopy(document)

    def delete(self, collection: str, key: str) -> bool:
        return self.collections.get(collection, {}).pop(key, None) is not None

    def change(self, collection: str, key: str, fn: Callable[[Document | None], Document | None]) -> Document | None:
        result = fn(self.get(collection, key))
        if result is None:
            self.delete(collection, key)
        else:
            self.put(collection, key, result)
        return copy.deepcopy(result)


class MemorySecrets:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def put(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> bool:
        return self.values.pop(name, None) is not None


@dataclass
class Message:
    to: str
    subject: str
    text: str
    html: str | None


@dataclass
class Outbox:
    """The panel's mailer, keeping what was sent in `messages`."""

    messages: list[Message] = field(default_factory=list)
    ready: bool = True

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        self.messages.append(Message(to, subject, text, html))


def settings_from_manifest(manifest: Manifest | None, overrides: Mapping[str, Any] | None = None) -> PluginSettings:
    """The settings a freshly installed plugin gets: each declared setting's default, then `overrides`."""
    values: dict[str, Any] = {}
    if manifest is not None:
        for setting in manifest.settings:
            values[setting.key] = setting.default
    values.update(overrides or {})
    return PluginSettings(values)


def make_context(
    plugin_id: str | Manifest = "com.example.plugin",
    *,
    settings: Mapping[str, Any] | None = None,
    permissions: Iterable[str] | None = None,
    data_dir: Path | None = None,
    services: FakeServices | None = None,
    version: str = "0.0.0",
    logger: logging.Logger | None = None,
) -> PluginContext:
    """A PluginContext for tests. Give a Manifest to take its id, version, defaults and permissions."""
    manifest = plugin_id if isinstance(plugin_id, Manifest) else None
    identifier = manifest.id if manifest else str(plugin_id)
    granted = frozenset(permissions if permissions is not None else (manifest.permissions if manifest else ()))
    if data_dir is None:
        raise ValueError("Give data_dir (pytest's tmp_path), so tests never write outside their own folder.")
    data_dir.mkdir(parents=True, exist_ok=True)
    return PluginContext(
        plugin_id=identifier,
        version=manifest.version if manifest else version,
        settings=settings_from_manifest(manifest, settings),
        services=services if services is not None else FakeServices(),
        logger=logger or logging.getLogger(f"sudoo.plugins.{identifier}"),
        data_dir=data_dir,
        permissions=granted,
        storage=MemoryStorage() if {"storage.read", "storage.write"} & granted else None,
        secrets=MemorySecrets() if "secrets" in granted else None,
        mail=Outbox() if "mail.send" in granted else None,
    )
