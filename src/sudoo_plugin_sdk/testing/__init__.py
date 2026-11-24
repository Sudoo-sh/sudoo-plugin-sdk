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
    """Make a caller as the core makes it for a person who is signed in.

    Args:
        *permissions: The panel permissions the person has.
        name: The person's name.

    Returns:
        The caller.
    """
    return Caller(name=name, permissions=frozenset(permissions), via="session")


def _need(caller: Caller, permission: str) -> None:
    """Check that a caller has a permission.

    Args:
        caller: The caller.
        permission: The permission.

    Raises:
        ServiceError: With status 403 when the caller lacks it.
    """
    if not caller.can(permission):
        raise ServiceError(403, "Not allowed", f"{caller.name} lacks {permission}.")


@dataclass
class Call:
    """One call recorded by the fake panel.

    Attributes:
        service: The service's name.
        method: The method's name.
        caller: The caller's name.
        arguments: The arguments, without the caller.
    """

    service: str
    method: str
    caller: str
    arguments: dict[str, Any]


class _Recorder:
    """Base of the fake services: records each call in a shared list."""

    def __init__(self, calls: list[Call], service: str) -> None:
        """Keep the shared list and the service's name.

        Args:
            calls: The list that receives each call.
            service: The service's name.
        """
        self._calls = calls
        self._service = service

    def _record(self, method: str, caller: Caller, **arguments: Any) -> None:
        """Record one call.

        Args:
            method: The method's name.
            caller: The caller.
            **arguments: The call's arguments.
        """
        self._calls.append(Call(self._service, method, caller.name, arguments))


class FakeInstances(_Recorder):
    """Fake instance service, in memory."""

    def __init__(self, calls: list[Call], jobs: FakeJobs, events: FakeEvents) -> None:
        """Create the service.

        Args:
            calls: The list that receives each call.
            jobs: The fake job service.
            events: The fake event service.
        """
        super().__init__(calls, "instances")
        self.items: dict[str, Resource] = {}
        self.logs_by_instance: dict[str, list[str]] = {}
        self._jobs = jobs
        self._events = events

    def add(self, name: str, **fields: Any) -> Resource:
        """Put an instance in the fake panel.

        Example: add("sales-main", branch="main", version="19.0").

        Args:
            name: The instance's name.
            **fields: Fields that replace the defaults.

        Returns:
            The stored resource.
        """
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
        """Find an instance.

        Args:
            name: The instance's name.

        Returns:
            The stored resource.

        Raises:
            ServiceError: With status 404 when there is none.
        """
        if name not in self.items:
            raise ServiceError(404, "Not found", f"No instance {name}.")
        return self.items[name]

    def list(self, caller: Caller, limit: int = 50, offset: int = 0) -> list[Resource]:
        """List instances; needs instances.view.

        Args:
            caller: Who asks.
            limit: The most instances to return.
            offset: How many to skip.

        Returns:
            Copies of the instances.
        """
        self._record("list", caller, limit=limit, offset=offset)
        _need(caller, "instances.view")
        return [copy.deepcopy(r) for r in list(self.items.values())[offset : offset + limit]]

    def get(self, caller: Caller, name: str) -> Resource:
        """Read one instance; needs instances.view.

        Args:
            caller: Who asks.
            name: The instance's name.

        Returns:
            A copy of the instance.
        """
        self._record("get", caller, name=name)
        _need(caller, "instances.view")
        return copy.deepcopy(self._find(name))

    def plan(
        self, caller: Caller, repo: str, branch: str, name: str | None = None, from_backup: str | None = None
    ) -> Resource:
        """Plan an instance; needs instances.create.

        Args:
            caller: Who asks.
            repo: The repository.
            branch: The branch.
            name: A name, or None to derive one from the branch.
            from_backup: A backup, or None.

        Returns:
            The plan.
        """
        self._record("plan", caller, repo=repo, branch=branch, name=name, from_backup=from_backup)
        _need(caller, "instances.create")
        chosen = name or branch.replace("/", "-").lower()
        return {"name": chosen, "database": chosen.replace("-", "_"), "quota_ok": True, "from_backup": from_backup}

    def quota(self, caller: Caller) -> Resource:
        """Read the quota; needs instances.view.

        Args:
            caller: Who asks.

        Returns:
            The number used and a limit of 0.
        """
        self._record("quota", caller)
        _need(caller, "instances.view")
        return {"used": len(self.items), "limit": 0}

    def create(self, caller: Caller, fields: Mapping[str, Any]) -> Resource:
        """Create an instance and emit "instance.created"; needs instances.create.

        Args:
            caller: Who asks.
            fields: The instance's fields.

        Returns:
            The job that was started.

        Raises:
            ServiceError: With status 409 when the name is taken.
        """
        self._record("create", caller, fields=dict(fields))
        _need(caller, "instances.create")
        name = str(fields.get("name") or str(fields.get("branch", "instance")).replace("/", "-"))
        if name in self.items:
            raise ServiceError(409, "Already exists", f"An instance {name} exists.")
        self.add(name, **{k: v for k, v in fields.items() if k != "name"}, status="creating")
        self._events.emit("instance.created", self.items[name])
        return self._jobs.start("create", name)

    def change(self, caller: Caller, name: str, fields: Mapping[str, Any]) -> Resource:
        """Change an instance; needs instances.update.

        Args:
            caller: Who asks.
            name: The instance's name.
            fields: The fields to change.

        Returns:
            A copy of the instance.
        """
        self._record("change", caller, name=name, fields=dict(fields))
        _need(caller, "instances.update")
        self._find(name).update(fields)
        return copy.deepcopy(self.items[name])

    def run(self, caller: Caller, name: str, action: str, fields: Mapping[str, Any] | None = None) -> Resource:
        """Run an action; the permission depends on the action.

        Args:
            caller: Who asks.
            name: The instance's name.
            action: The action's name.
            fields: Extra fields, or None.

        Returns:
            The job that was started.
        """
        self._record("run", caller, name=name, action=action, fields=dict(fields or {}))
        permission = {"backup": "instances.operate", "pause": "instances.operate", "restore": "instances.restore"}
        _need(caller, permission.get(action, "instances.update"))
        self._find(name)
        return self._jobs.start(action, name)

    def delete(self, caller: Caller, name: str, confirm: str) -> Resource:
        """Delete an instance and emit "instance.deleted"; needs instances.delete.

        Args:
            caller: Who asks.
            name: The instance's name.
            confirm: The confirmation text, which must equal the name.

        Returns:
            The job that was started.

        Raises:
            ServiceError: With status 422 when the confirmation does not match.
        """
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
        """Read fixed test credentials; needs instances.credentials.

        Args:
            caller: Who asks.
            name: The instance's name.

        Returns:
            A login and a password.
        """
        self._record("credentials", caller, name=name)
        _need(caller, "instances.credentials")
        self._find(name)
        return {"login": "admin", "password": "test-password"}

    def logs(self, caller: Caller, name: str, lines: int = 200) -> builtins.list[str]:
        """Read log lines kept for the instance; needs instances.logs.

        Args:
            caller: Who asks.
            name: The instance's name.
            lines: The most lines to return.

        Returns:
            The last lines.
        """
        self._record("logs", caller, name=name, lines=lines)
        _need(caller, "instances.logs")
        self._find(name)
        return self.logs_by_instance.get(name, [])[-lines:]


class FakeJobs(_Recorder):
    """Fake job service, in memory."""

    def __init__(self, calls: list[Call]) -> None:
        """Create the service.

        Args:
            calls: The list that receives each call.
        """
        super().__init__(calls, "jobs")
        self.items: dict[str, Resource] = {}
        self._ids = itertools.count(1)

    def start(self, kind: str, instance: str, status: str = "success") -> Resource:
        """A job the fake panel ran (finished at once, with `status`)."""
        job_id = f"job{next(self._ids):04d}"
        self.items[job_id] = {"id": job_id, "kind": kind, "instance": instance, "status": status, "log": ""}
        return copy.deepcopy(self.items[job_id])

    def _find(self, job_id: str) -> Resource:
        """Find a job.

        Args:
            job_id: The job's id.

        Returns:
            The stored resource.

        Raises:
            ServiceError: With status 404 when there is none.
        """
        if job_id not in self.items:
            raise ServiceError(404, "Not found", f"No job {job_id}.")
        return self.items[job_id]

    def list(self, caller: Caller, instance: str | None = None, limit: int = 50, offset: int = 0) -> list[Resource]:
        """List jobs; needs instances.view.

        Args:
            caller: Who asks.
            instance: Only jobs of this instance, or None.
            limit: The most jobs to return.
            offset: How many to skip.

        Returns:
            Copies of the jobs.
        """
        self._record("list", caller, instance=instance, limit=limit, offset=offset)
        _need(caller, "instances.view")
        rows = [j for j in self.items.values() if instance is None or j["instance"] == instance]
        return [copy.deepcopy(j) for j in rows[offset : offset + limit]]

    def get(self, caller: Caller, job_id: str, include_log: bool = False) -> Resource:
        """Read one job; needs instances.view.

        Args:
            caller: Who asks.
            job_id: The job's id.
            include_log: True to keep the log in the result.

        Returns:
            A copy of the job.
        """
        self._record("get", caller, job_id=job_id, include_log=include_log)
        _need(caller, "instances.view")
        job = copy.deepcopy(self._find(job_id))
        if not include_log:
            job.pop("log", None)
        return job

    def log(self, caller: Caller, job_id: str, offset: int = 0) -> Resource:
        """Read a job's log; needs instances.logs.

        Args:
            caller: Who asks.
            job_id: The job's id.
            offset: Where to start reading.

        Returns:
            The text from the offset, and the new offset.
        """
        self._record("log", caller, job_id=job_id, offset=offset)
        _need(caller, "instances.logs")
        text = str(self._find(job_id).get("log", ""))
        return {"text": text[offset:], "offset": len(text)}

    def wait(self, caller: Caller, job_id: str, timeout: float = 60.0) -> Resource:
        """Return a job at once, because fake jobs are already finished; needs instances.view.

        Args:
            caller: Who asks.
            job_id: The job's id.
            timeout: Not used.

        Returns:
            A copy of the job.
        """
        self._record("wait", caller, job_id=job_id, timeout=timeout)
        _need(caller, "instances.view")
        return copy.deepcopy(self._find(job_id))


class FakeBackups(_Recorder):
    """Fake backup service, in memory."""

    def __init__(self, calls: list[Call]) -> None:
        """Create the service.

        Args:
            calls: The list that receives each call.
        """
        super().__init__(calls, "backups")
        self.items: list[Resource] = []

    def add(self, file: str, instance: str, version: str = "19.0", **fields: Any) -> Resource:
        """Put a backup in the fake panel.

        Args:
            file: The backup's file name.
            instance: The instance it belongs to.
            version: The Odoo version.
            **fields: More fields.

        Returns:
            The backup.
        """
        resource: Resource = {"file": file, "instance": instance, "version": version, "size": 0} | fields
        self.items.append(resource)
        return resource

    def list(self, caller: Caller, instance: str | None = None, version: str | None = None) -> list[Resource]:
        """List backups. Without backups.manage the caller needs instances.view and must name an instance.

        Args:
            caller: Who asks.
            instance: Only backups of this instance, or None.
            version: Only backups of this version, or None.

        Returns:
            Copies of the backups.
        """
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
        """Tell whether a backup of that file and version exists; needs instances.view.

        Args:
            caller: Who asks.
            file: The backup's file name.
            version: The Odoo version.

        Returns:
            True when there is one.
        """
        self._record("compatible", caller, file=file, version=version)
        _need(caller, "instances.view")
        return any(b["file"] == file and b["version"] == version for b in self.items)

    def delete(self, caller: Caller, file: str) -> None:
        """Delete a backup; needs backups.manage.

        Args:
            caller: Who asks.
            file: The backup's file name.
        """
        self._record("delete", caller, file=file)
        _need(caller, "backups.manage")
        self.items = [b for b in self.items if b["file"] != file]


class FakeVersions(_Recorder):
    """Fake version service, with Odoo 17.0, 18.0 and 19.0."""

    def __init__(self, calls: list[Call]) -> None:
        """Create the service.

        Args:
            calls: The list that receives each call.
        """
        super().__init__(calls, "versions")
        self.items: list[Resource] = [
            {"version": "17.0", "enterprise": False},
            {"version": "18.0", "enterprise": False},
            {"version": "19.0", "enterprise": False},
        ]

    def list(self, caller: Caller) -> list[Resource]:
        """List the versions.

        Args:
            caller: Who asks.

        Returns:
            Copies of the versions.
        """
        self._record("list", caller)
        return copy.deepcopy(self.items)


class FakeDocs(_Recorder):
    """Fake documentation service, in memory."""

    def __init__(self, calls: list[Call]) -> None:
        """Create the service.

        Args:
            calls: The list that receives each call.
        """
        super().__init__(calls, "docs")
        self.pages: dict[str, str] = {}

    def list(self, caller: Caller) -> list[Resource]:
        """List the pages.

        Args:
            caller: Who asks.

        Returns:
            The paths, sorted.
        """
        self._record("list", caller)
        return [{"path": path} for path in sorted(self.pages)]

    def get(self, caller: Caller, path: str) -> Resource:
        """Read one page.

        Args:
            caller: Who asks.
            path: The page's path.

        Returns:
            The path and the text.

        Raises:
            ServiceError: With status 404 when there is no such page.
        """
        self._record("get", caller, path=path)
        if path not in self.pages:
            raise ServiceError(404, "Not found", f"No page {path}.")
        return {"path": path, "text": self.pages[path]}


class FakeServer(_Recorder):
    """Fake server service, with fixed figures."""

    def __init__(self, calls: list[Call]) -> None:
        """Create the service.

        Args:
            calls: The list that receives each call.
        """
        super().__init__(calls, "server")
        self.values: Resource = {"cpu_percent": 6.0, "memory_percent": 41.0, "disk_percent": 37.0}

    def figures(self, caller: Caller) -> Resource:
        """Read the figures; needs instances.view.

        Args:
            caller: Who asks.

        Returns:
            A copy of the figures.
        """
        self._record("figures", caller)
        _need(caller, "instances.view")
        return copy.deepcopy(self.values)


class FakeEvents:
    """Fake event service: keeps what was emitted and calls subscribers."""

    def __init__(self) -> None:
        """Create the service with no subscribers."""
        self._subscribers: list[tuple[frozenset[str], Callable[[Event], None]]] = []
        self.sent: list[Event] = []

    def subscribe(self, kinds: list[str], callback: Callable[[Event], None]) -> Unsubscribe:
        """Subscribe to events.

        Args:
            kinds: The event kinds to listen for; an empty list means every kind.
            callback: Called with each event.

        Returns:
            A function that ends the subscription.
        """
        entry = (frozenset(kinds), callback)
        self._subscribers.append(entry)

        def unsubscribe() -> None:
            """Remove the subscription, if it is still there."""
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
    """Fake route service, with two example routes."""

    def __init__(self) -> None:
        """Create the service with the example routes."""
        self.items: list[RouteInfo] = [
            RouteInfo("GET", "/api/v1/instances", "instances.view", "List instances"),
            RouteInfo("POST", "/api/v1/instances", "instances.create", "Create an instance"),
        ]

    def list(self) -> list[RouteInfo]:
        """List the routes.

        Returns:
            A copy of the list.
        """
        return list(self.items)


class FakeServices:
    """The services of a fake panel (`context.services`).

    Every call is recorded in `calls`; permissions are checked like the
    panel does (a ServiceError 403 when the caller lacks one).
    """

    def __init__(self) -> None:
        """Create the fake services, sharing one list of calls."""
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
        """The fake instance service.

        Returns:
            The service.
        """
        return self._instances

    @property
    def jobs(self) -> FakeJobs:
        """The fake job service.

        Returns:
            The service.
        """
        return self._jobs

    @property
    def backups(self) -> FakeBackups:
        """The fake backup service.

        Returns:
            The service.
        """
        return self._backups

    @property
    def versions(self) -> FakeVersions:
        """The fake version service.

        Returns:
            The service.
        """
        return self._versions

    @property
    def docs(self) -> FakeDocs:
        """The fake documentation service.

        Returns:
            The service.
        """
        return self._docs

    @property
    def server(self) -> FakeServer:
        """The fake server service.

        Returns:
            The service.
        """
        return self._server

    @property
    def events(self) -> FakeEvents:
        """The fake event service.

        Returns:
            The service.
        """
        return self._events

    @property
    def routes(self) -> FakeRoutes:
        """The fake route service.

        Returns:
            The service.
        """
        return self._routes


class MemoryStorage:
    """The plugin's own records, in memory."""

    def __init__(self) -> None:
        """Create empty storage."""
        self.collections: dict[str, dict[str, Document]] = {}

    def get(self, collection: str, key: str) -> Document | None:
        """Read one record.

        Args:
            collection: The collection's name.
            key: The record's key.

        Returns:
            A copy of the record, or None.
        """
        found = self.collections.get(collection, {}).get(key)
        return copy.deepcopy(found)

    def all(self, collection: str) -> dict[str, Document]:
        """Read a whole collection.

        Args:
            collection: The collection's name.

        Returns:
            A copy of the records by key.
        """
        return copy.deepcopy(self.collections.get(collection, {}))

    def put(self, collection: str, key: str, document: Document) -> None:
        """Write one record.

        Args:
            collection: The collection's name.
            key: The record's key.
            document: The record; a copy is kept.
        """
        self.collections.setdefault(collection, {})[key] = copy.deepcopy(document)

    def delete(self, collection: str, key: str) -> bool:
        """Delete one record.

        Args:
            collection: The collection's name.
            key: The record's key.

        Returns:
            True when there was a record.
        """
        return self.collections.get(collection, {}).pop(key, None) is not None

    def change(self, collection: str, key: str, fn: Callable[[Document | None], Document | None]) -> Document | None:
        """Change one record with a function.

        Args:
            collection: The collection's name.
            key: The record's key.
            fn: Gets the current record (None when there is none). Returns the new record, or None to delete it.

        Returns:
            A copy of the record after the change.
        """
        result = fn(self.get(collection, key))
        if result is None:
            self.delete(collection, key)
        else:
            self.put(collection, key, result)
        return copy.deepcopy(result)


class MemorySecrets:
    """Secrets vault, in memory."""

    def __init__(self) -> None:
        """Create an empty vault."""
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        """Read a secret.

        Args:
            name: The secret's name.

        Returns:
            The value, or None.
        """
        return self.values.get(name)

    def put(self, name: str, value: str) -> None:
        """Store a secret.

        Args:
            name: The secret's name.
            value: The value.
        """
        self.values[name] = value

    def delete(self, name: str) -> bool:
        """Delete a secret.

        Args:
            name: The secret's name.

        Returns:
            True when there was a secret.
        """
        return self.values.pop(name, None) is not None


@dataclass
class Message:
    """One message kept by the `Outbox`.

    Attributes:
        to: The recipient.
        subject: The subject line.
        text: The plain-text body.
        html: The HTML body, or None.
    """

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
        """Keep a message instead of sending it.

        Args:
            to: The recipient.
            subject: The subject line.
            text: The plain-text body.
            html: The HTML body, or None.
        """
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
