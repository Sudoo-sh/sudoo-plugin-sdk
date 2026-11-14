"""What the panel gives every plugin: its settings, the core services, a logger, a data folder and its own records.

The panel creates each plugin class once, with a `PluginContext` (dependency injection: a plugin never reads the
environment, imports Flask or reaches into the panel's modules). Everything a plugin may do to the panel goes through
`context.services`, the stable service layer the panel's own routes use, so a plugin gets exactly the checks, audit
entries and quotas the web app gets.

The service signatures below follow ROADMAP section 11 ("Core service layer"). They are versioned with this SDK
(`sdk_version` in manifest.json): a breaking change is a new major SDK version.
"""

from __future__ import annotations

import builtins
import logging
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

Resource = dict[str, Any]
"""A plain dictionary, the same shape as the panel's API resources (never passwords)."""

Via = Literal["session", "token", "mcp", "plugin"]


@dataclass(frozen=True, slots=True)
class Caller:
    """Who asks the services to do something. The core builds it for people signed in to the web app; an
    `api_access` plugin builds it for tokens; a plugin acting on its own behalf uses `PluginContext.caller`."""

    name: str  # "sam", "api:CI pipeline", "mcp:Sam's laptop", "plugin:com.example.backup"
    permissions: frozenset[str]
    via: Via = "session"
    token_id: str | None = None
    ip: str = ""
    request_id: str = ""

    def can(self, permission: str) -> bool:
        return permission in self.permissions


class ServiceError(Exception):
    """The only exception a service raises. The panel turns it into RFC 9457 problem details for the API, and the
    MCP plugin into a tool error."""

    def __init__(self, status: int, title: str, detail: str = "") -> None:
        super().__init__(f"{status} {title}" + (f": {detail}" if detail else ""))
        self.status = status
        self.title = title
        self.detail = detail


# --------------------------------------------------------------------------- services


@runtime_checkable
class InstanceService(Protocol):
    def list(self, caller: Caller, limit: int = 50, offset: int = 0) -> list[Resource]: ...
    def get(self, caller: Caller, name: str) -> Resource: ...
    def plan(
        self, caller: Caller, repo: str, branch: str, name: str | None = None, from_backup: str | None = None
    ) -> Resource: ...
    def quota(self, caller: Caller) -> Resource: ...
    def create(self, caller: Caller, fields: Mapping[str, Any]) -> Resource: ...
    def change(self, caller: Caller, name: str, fields: Mapping[str, Any]) -> Resource: ...
    def run(self, caller: Caller, name: str, action: str, fields: Mapping[str, Any] | None = None) -> Resource: ...
    def delete(self, caller: Caller, name: str, confirm: str) -> Resource: ...
    def credentials(self, caller: Caller, name: str) -> Resource: ...
    def logs(self, caller: Caller, name: str, lines: int = 200) -> builtins.list[str]: ...


@runtime_checkable
class JobService(Protocol):
    def list(self, caller: Caller, instance: str | None = None, limit: int = 50, offset: int = 0) -> list[Resource]: ...
    def get(self, caller: Caller, job_id: str, include_log: bool = False) -> Resource: ...
    def log(self, caller: Caller, job_id: str, offset: int = 0) -> Resource: ...
    def wait(self, caller: Caller, job_id: str, timeout: float = 60.0) -> Resource: ...


@runtime_checkable
class BackupService(Protocol):
    def list(self, caller: Caller, instance: str | None = None, version: str | None = None) -> list[Resource]: ...
    def compatible(self, caller: Caller, file: str, version: str) -> bool: ...
    def delete(self, caller: Caller, file: str) -> None: ...


@runtime_checkable
class VersionService(Protocol):
    def list(self, caller: Caller) -> list[Resource]: ...


@runtime_checkable
class DocsService(Protocol):
    def list(self, caller: Caller) -> list[Resource]: ...
    def get(self, caller: Caller, path: str) -> Resource: ...


@runtime_checkable
class ServerService(Protocol):
    def figures(self, caller: Caller) -> Resource: ...


Event = dict[str, Any]
"""{"kind": "instance.created", "data": {...}}: instance, job and backup events, presented as API resources."""

Unsubscribe = Callable[[], None]


@runtime_checkable
class EventService(Protocol):
    def subscribe(self, kinds: list[str], callback: Callable[[Event], None]) -> Unsubscribe: ...


@dataclass(frozen=True, slots=True)
class RouteInfo:
    method: str
    path: str
    permission: str | None
    summary: str = ""


@runtime_checkable
class RouteService(Protocol):
    def list(self) -> list[RouteInfo]: ...


@runtime_checkable
class Services(Protocol):
    """`sudoo.services`: what the core offers plugins. Every call checks the caller's permission and writes the
    audit entry itself."""

    @property
    def instances(self) -> InstanceService: ...
    @property
    def jobs(self) -> JobService: ...
    @property
    def backups(self) -> BackupService: ...
    @property
    def versions(self) -> VersionService: ...
    @property
    def docs(self) -> DocsService: ...
    @property
    def server(self) -> ServerService: ...
    @property
    def events(self) -> EventService: ...
    @property
    def routes(self) -> RouteService: ...


# --------------------------------------------------------------------------- the plugin's own things

Document = dict[str, Any]


@runtime_checkable
class PluginStorage(Protocol):
    """The plugin's own records (permissions `storage.read` / `storage.write`), kept by the panel's storage and
    separate from every other plugin's. Collections are names the plugin chooses."""

    def get(self, collection: str, key: str) -> Document | None: ...
    def all(self, collection: str) -> dict[str, Document]: ...
    def put(self, collection: str, key: str, document: Document) -> None: ...
    def delete(self, collection: str, key: str) -> bool: ...
    def change(
        self, collection: str, key: str, fn: Callable[[Document | None], Document | None]
    ) -> Document | None: ...


@runtime_checkable
class Secrets(Protocol):
    """The panel's encrypted vault (permission `secrets`), one namespace per plugin."""

    def get(self, name: str) -> str | None: ...
    def put(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> bool: ...


@runtime_checkable
class Mail(Protocol):
    """The panel's mailer (permission `mail.send`)."""

    @property
    def ready(self) -> bool: ...
    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None: ...


class PluginSettings(Mapping[str, Any]):
    """The values of the settings the manifest declares, as the administrator set them on the Settings page
    (defaults otherwise). Read-only for the plugin; secrets are plain strings here and never logged by the panel."""

    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        self._values = dict(values or {})

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"PluginSettings({sorted(self._values)})"  # keys only: values may be secrets

    def string(self, key: str, default: str = "") -> str:
        value = self._values.get(key, default)
        return default if value is None else str(value)

    def integer(self, key: str, default: int = 0) -> int:
        value = self._values.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"The setting {key} must be a whole number.")
        return value

    def number(self, key: str, default: float = 0.0) -> float:
        value = self._values.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"The setting {key} must be a number.")
        return float(value)

    def boolean(self, key: str, default: bool = False) -> bool:
        value = self._values.get(key, default)
        if not isinstance(value, bool):
            raise ValueError(f"The setting {key} must be true or false.")
        return value


# What each plugin permission lets the plugin's own Caller do in the services (the panel's role permissions).
PLUGIN_GRANTS: dict[str, frozenset[str]] = {
    "instances.read": frozenset({"instances.view", "instances.logs"}),
    "instances.write": frozenset(
        {"instances.view", "instances.create", "instances.update", "instances.operate", "instances.restore",
         "instances.delete", "backups.manage"}
    ),
    "accounts.read": frozenset({"accounts.view"}),
    "settings.read": frozenset({"settings.view"}),
    "settings.write": frozenset({"settings.view", "settings.manage"}),
}  # fmt: skip


def granted(permissions: frozenset[str]) -> frozenset[str]:
    """The panel permissions a plugin's own Caller has, from the plugin permissions it was granted."""
    result: set[str] = set()
    for permission in permissions:
        result |= PLUGIN_GRANTS.get(permission, frozenset())
    return frozenset(result)


@dataclass(frozen=True)
class PluginContext:
    """Everything the panel hands a plugin when it creates it."""

    plugin_id: str
    version: str
    settings: PluginSettings
    services: Services
    logger: logging.Logger
    data_dir: Path  # a folder only this plugin writes to; kept across updates, removed on uninstall
    permissions: frozenset[str] = field(default_factory=frozenset)  # granted at install (the manifest's list)
    storage: PluginStorage | None = None  # with storage.read / storage.write
    secrets: Secrets | None = None  # with secrets
    mail: Mail | None = None  # with mail.send
    sudoo_version: str = "2.0.0"

    @property
    def caller(self) -> Caller:
        """The Caller for things the plugin does on its own (a background task, an instance hook): limited to what
        the permissions granted at install allow (PLUGIN_GRANTS), audited as plugin:<id>."""
        return Caller(name=f"plugin:{self.plugin_id}", permissions=granted(self.permissions), via="plugin")

    def require(self, permission: str) -> None:
        """Raise PermissionError when the plugin was not granted `permission`; call before using a capability."""
        if permission not in self.permissions:
            raise PermissionError(f"{self.plugin_id} was not granted the permission {permission}.")
