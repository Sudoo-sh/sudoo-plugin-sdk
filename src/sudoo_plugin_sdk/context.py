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

# How a caller reached the panel: "session" (a person in the web app), "token" (an API token), "mcp" or "plugin".
Via = Literal["session", "token", "mcp", "plugin"]


@dataclass(frozen=True, slots=True)
class Caller:
    """Who asks the services to do something.

    The core builds it for people signed in to the web app; an `api_access` plugin builds it for tokens; a plugin
    acting on its own behalf uses `PluginContext.caller`.

    Attributes:
        name: Who it is, for example "sam", "api:CI pipeline", "mcp:Sam's laptop" or "plugin:com.example.backup".
        permissions: The panel permissions the caller has.
        via: How the caller reached the panel. Default "session".
        token_id: The id of the API token used, or None.
        ip: The caller's IP address; "" when unknown.
        request_id: The id of the request, for the logs; "" when there is none.
    """

    name: str  # "sam", "api:CI pipeline", "mcp:Sam's laptop", "plugin:com.example.backup"
    permissions: frozenset[str]
    via: Via = "session"
    token_id: str | None = None
    ip: str = ""
    request_id: str = ""

    def can(self, permission: str) -> bool:
        """Tell whether the caller has a permission.

        Args:
            permission: The panel permission to look for.

        Returns:
            True when the caller has it.
        """
        return permission in self.permissions


class ServiceError(Exception):
    """The only exception a service raises.

    The panel turns it into RFC 9457 problem details for the API, and the MCP plugin into a tool error.

    Attributes:
        status: The HTTP status code that fits the error.
        title: A short title.
        detail: A longer explanation; empty when there is none.
    """

    def __init__(self, status: int, title: str, detail: str = "") -> None:
        """Create the error.

        Args:
            status: The HTTP status code that fits the error.
            title: A short title.
            detail: A longer explanation.
        """
        super().__init__(f"{status} {title}" + (f": {detail}" if detail else ""))
        self.status = status
        self.title = title
        self.detail = detail


# --------------------------------------------------------------------------- services


@runtime_checkable
class InstanceService(Protocol):
    """Service for instances. Every method takes the `Caller` first."""

    def list(self, caller: Caller, limit: int = 50, offset: int = 0) -> list[Resource]:
        """List instances.

        Args:
            caller: Who asks.
            limit: The most instances to return.
            offset: How many to skip.

        Returns:
            The instances, as API resources.
        """
        ...

    def get(self, caller: Caller, name: str) -> Resource:
        """Read one instance.

        Args:
            caller: Who asks.
            name: The instance's name.

        Returns:
            The instance, as an API resource.
        """
        ...

    def plan(
        self, caller: Caller, repo: str, branch: str, name: str | None = None, from_backup: str | None = None
    ) -> Resource:
        """Work out what creating an instance from a repository branch would do, without creating it.

        Args:
            caller: Who asks.
            repo: The repository.
            branch: The branch.
            name: A name for the instance, or None.
            from_backup: A backup to start from, or None.

        Returns:
            The plan, as an API resource.
        """
        ...

    def quota(self, caller: Caller) -> Resource:
        """Read the instance limits that apply to the caller.

        Args:
            caller: Who asks.

        Returns:
            The quota, as an API resource.
        """
        ...

    def create(self, caller: Caller, fields: Mapping[str, Any]) -> Resource:
        """Create an instance.

        Args:
            caller: Who asks.
            fields: The instance's fields.

        Returns:
            The result, as an API resource.
        """
        ...

    def change(self, caller: Caller, name: str, fields: Mapping[str, Any]) -> Resource:
        """Change an instance's settings.

        Args:
            caller: Who asks.
            name: The instance's name.
            fields: The fields to change.

        Returns:
            The instance, as an API resource.
        """
        ...

    def run(self, caller: Caller, name: str, action: str, fields: Mapping[str, Any] | None = None) -> Resource:
        """Run an action on an instance.

        Args:
            caller: Who asks.
            name: The instance's name.
            action: The action's name.
            fields: Extra fields for the action, or None.

        Returns:
            The result, as an API resource.
        """
        ...

    def delete(self, caller: Caller, name: str, confirm: str) -> Resource:
        """Delete an instance.

        Args:
            caller: Who asks.
            name: The instance's name.
            confirm: The confirmation text.

        Returns:
            The result, as an API resource.
        """
        ...

    def credentials(self, caller: Caller, name: str) -> Resource:
        """Read an instance's credentials.

        Args:
            caller: Who asks.
            name: The instance's name.

        Returns:
            The credentials, as an API resource.
        """
        ...

    def logs(self, caller: Caller, name: str, lines: int = 200) -> builtins.list[str]:
        """Read the end of an instance's log.

        Args:
            caller: Who asks.
            name: The instance's name.
            lines: How many lines to return.

        Returns:
            The log lines.
        """
        ...


@runtime_checkable
class JobService(Protocol):
    """Service for jobs. Every method takes the `Caller` first."""

    def list(self, caller: Caller, instance: str | None = None, limit: int = 50, offset: int = 0) -> list[Resource]:
        """List jobs.

        Args:
            caller: Who asks.
            instance: Only jobs of this instance, or None for all.
            limit: The most jobs to return.
            offset: How many to skip.

        Returns:
            The jobs, as API resources.
        """
        ...

    def get(self, caller: Caller, job_id: str, include_log: bool = False) -> Resource:
        """Read one job.

        Args:
            caller: Who asks.
            job_id: The job's id.
            include_log: True to include its technical log.

        Returns:
            The job, as an API resource.
        """
        ...

    def log(self, caller: Caller, job_id: str, offset: int = 0) -> Resource:
        """Read a job's technical log.

        Args:
            caller: Who asks.
            job_id: The job's id.
            offset: Where to start reading.

        Returns:
            The log, as an API resource.
        """
        ...

    def wait(self, caller: Caller, job_id: str, timeout: float = 60.0) -> Resource:
        """Wait for a job.

        Args:
            caller: Who asks.
            job_id: The job's id.
            timeout: How many seconds to wait at most.

        Returns:
            The job, as an API resource.
        """
        ...


@runtime_checkable
class BackupService(Protocol):
    """Service for backups. Every method takes the `Caller` first."""

    def list(self, caller: Caller, instance: str | None = None, version: str | None = None) -> list[Resource]:
        """List backups.

        Args:
            caller: Who asks.
            instance: Only backups of this instance, or None for all.
            version: Only backups of this Odoo version, or None for all.

        Returns:
            The backups, as API resources.
        """
        ...

    def compatible(self, caller: Caller, file: str, version: str) -> bool:
        """Tell whether a backup can be restored into an Odoo version.

        Args:
            caller: Who asks.
            file: The backup's file name.
            version: The Odoo version.

        Returns:
            True when it is compatible.
        """
        ...

    def delete(self, caller: Caller, file: str) -> None:
        """Delete a backup.

        Args:
            caller: Who asks.
            file: The backup's file name.
        """
        ...


@runtime_checkable
class VersionService(Protocol):
    """Service for the Odoo versions the panel offers."""

    def list(self, caller: Caller) -> list[Resource]:
        """List the Odoo versions.

        Args:
            caller: Who asks.

        Returns:
            The versions, as API resources.
        """
        ...


@runtime_checkable
class DocsService(Protocol):
    """Service for the panel's documentation pages."""

    def list(self, caller: Caller) -> list[Resource]:
        """List the documentation pages.

        Args:
            caller: Who asks.

        Returns:
            The pages, as API resources.
        """
        ...

    def get(self, caller: Caller, path: str) -> Resource:
        """Read one documentation page.

        Args:
            caller: Who asks.
            path: The page's path.

        Returns:
            The page, as an API resource.
        """
        ...


@runtime_checkable
class ServerService(Protocol):
    """Service for figures about the server."""

    def figures(self, caller: Caller) -> Resource:
        """Read the server's figures.

        Args:
            caller: Who asks.

        Returns:
            The figures, as an API resource.
        """
        ...


Event = dict[str, Any]
"""{"kind": "instance.created", "data": {...}}: instance, job and backup events, presented as API resources."""

# A function without arguments that stops a subscription.
Unsubscribe = Callable[[], None]


@runtime_checkable
class EventService(Protocol):
    """Service for events."""

    def subscribe(self, kinds: list[str], callback: Callable[[Event], None]) -> Unsubscribe:
        """Call a function for events of some kinds.

        Args:
            kinds: The kinds of event to listen for, for example "instance.created".
            callback: Called with each event.

        Returns:
            A function that ends the subscription.
        """
        ...


@dataclass(frozen=True, slots=True)
class RouteInfo:
    """One API route of the panel.

    Attributes:
        method: The HTTP method.
        path: The route's path.
        permission: The permission a caller needs, or None.
        summary: A one-line description; empty by default.
    """

    method: str
    path: str
    permission: str | None
    summary: str = ""


@runtime_checkable
class RouteService(Protocol):
    """Service for the panel's API routes."""

    def list(self) -> list[RouteInfo]:
        """List the routes.

        Returns:
            The routes.
        """
        ...


@runtime_checkable
class Services(Protocol):
    """`sudoo.services`: what the core offers plugins.

    Every call checks the caller's permission and writes the audit entry itself.

    Attributes:
        instances: Service for instances.
        jobs: Service for jobs.
        backups: Service for backups.
        versions: Service for Odoo versions.
        docs: Service for documentation pages.
        server: Service for server figures.
        events: Service for events.
        routes: Service for API routes.
    """

    @property
    def instances(self) -> InstanceService:
        """Service for instances."""
        ...

    @property
    def jobs(self) -> JobService:
        """Service for jobs."""
        ...

    @property
    def backups(self) -> BackupService:
        """Service for backups."""
        ...

    @property
    def versions(self) -> VersionService:
        """Service for Odoo versions."""
        ...

    @property
    def docs(self) -> DocsService:
        """Service for documentation pages."""
        ...

    @property
    def server(self) -> ServerService:
        """Service for server figures."""
        ...

    @property
    def events(self) -> EventService:
        """Service for events."""
        ...

    @property
    def routes(self) -> RouteService:
        """Service for API routes."""
        ...


# --------------------------------------------------------------------------- the plugin's own things

# A record kept in plugin storage, as a dictionary.
Document = dict[str, Any]


@runtime_checkable
class PluginStorage(Protocol):
    """The plugin's own records (permissions `storage.read` / `storage.write`).

    Kept by the panel's storage and separate from every other plugin's. Collections are names the plugin chooses.
    """

    def get(self, collection: str, key: str) -> Document | None:
        """Read one record.

        Args:
            collection: The collection's name.
            key: The record's key.

        Returns:
            The record, or None when there is none.
        """
        ...

    def all(self, collection: str) -> dict[str, Document]:
        """Read a whole collection.

        Args:
            collection: The collection's name.

        Returns:
            The records by key.
        """
        ...

    def put(self, collection: str, key: str, document: Document) -> None:
        """Write one record.

        Args:
            collection: The collection's name.
            key: The record's key.
            document: The record.
        """
        ...

    def delete(self, collection: str, key: str) -> bool:
        """Delete one record.

        Args:
            collection: The collection's name.
            key: The record's key.

        Returns:
            True when there was a record to delete.
        """
        ...

    def change(self, collection: str, key: str, fn: Callable[[Document | None], Document | None]) -> Document | None:
        """Change one record: the function gets the current record and returns the new one.

        Args:
            collection: The collection's name.
            key: The record's key.
            fn: Called with the current record (None when there is none). It returns the new record, or None.

        Returns:
            The record after the change, or None.
        """
        ...


@runtime_checkable
class Secrets(Protocol):
    """The panel's encrypted vault (permission `secrets`), one namespace per plugin."""

    def get(self, name: str) -> str | None:
        """Read a secret.

        Args:
            name: The secret's name.

        Returns:
            The value, or None when there is none.
        """
        ...

    def put(self, name: str, value: str) -> None:
        """Store a secret.

        Args:
            name: The secret's name.
            value: The value.
        """
        ...

    def delete(self, name: str) -> bool:
        """Delete a secret.

        Args:
            name: The secret's name.

        Returns:
            True when there was a secret to delete.
        """
        ...


@runtime_checkable
class Mail(Protocol):
    """The panel's mailer (permission `mail.send`)."""

    @property
    def ready(self) -> bool:
        """Whether the mailer is configured and can send.

        Returns:
            True when it can.
        """
        ...

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        """Send one message.

        Args:
            to: The recipient's address.
            subject: The subject line.
            text: The plain-text body.
            html: An HTML body, or None.
        """
        ...


class PluginSettings(Mapping[str, Any]):
    """The values of the settings the manifest declares.

    These are the values the administrator set on the Settings page (defaults otherwise). Read-only for the plugin; secrets are plain strings here and never logged by the panel.
    """

    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        """Keep a copy of the values.

        Args:
            values: The settings by key, or None for none.
        """
        self._values = dict(values or {})

    def __getitem__(self, key: str) -> Any:
        """Read a setting.

        Args:
            key: The setting's key.

        Returns:
            The value.

        Raises:
            KeyError: When there is no such setting.
        """
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        """Iterate over the setting keys.

        Returns:
            An iterator of keys.
        """
        return iter(self._values)

    def __len__(self) -> int:
        """Count the settings.

        Returns:
            The number of settings.
        """
        return len(self._values)

    def __repr__(self) -> str:
        """Show the keys only: the values may be secrets.

        Returns:
            The text.
        """
        return f"PluginSettings({sorted(self._values)})"  # keys only: values may be secrets

    def string(self, key: str, default: str = "") -> str:
        """Read a setting as text.

        Args:
            key: The setting's key.
            default: The value when the setting is missing. It is also used when the stored value is None.

        Returns:
            The value as text.
        """
        value = self._values.get(key, default)
        return default if value is None else str(value)

    def integer(self, key: str, default: int = 0) -> int:
        """Read a setting as a whole number.

        Args:
            key: The setting's key.
            default: The value when the setting is missing.

        Returns:
            The value.

        Raises:
            ValueError: When the value is not a whole number (a boolean does not count).
        """
        value = self._values.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"The setting {key} must be a whole number.")
        return value

    def number(self, key: str, default: float = 0.0) -> float:
        """Read a setting as a number.

        Args:
            key: The setting's key.
            default: The value when the setting is missing.

        Returns:
            The value as a float.

        Raises:
            ValueError: When the value is not a number (a boolean does not count).
        """
        value = self._values.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"The setting {key} must be a number.")
        return float(value)

    def boolean(self, key: str, default: bool = False) -> bool:
        """Read a setting as true or false.

        Args:
            key: The setting's key.
            default: The value when the setting is missing.

        Returns:
            The value.

        Raises:
            ValueError: When the value is not a boolean.
        """
        value = self._values.get(key, default)
        if not isinstance(value, bool):
            raise ValueError(f"The setting {key} must be true or false.")
        return value


# What each plugin permission lets the plugin's own Caller do in the services (the panel's role permissions).
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
    """The panel permissions a plugin's own Caller has, from the plugin permissions it was granted.

    Args:
        permissions: The plugin permissions granted at install.

    Returns:
        The panel permissions they stand for (see `PLUGIN_GRANTS`). Permissions without an entry add nothing.
    """
    result: set[str] = set()
    for permission in permissions:
        result |= PLUGIN_GRANTS.get(permission, frozenset())
    return frozenset(result)


@dataclass(frozen=True)
class PluginContext:
    """Everything the panel hands a plugin when it creates it.

    Attributes:
        plugin_id: The plugin's id.
        version: The installed version of the plugin.
        settings: The values of the plugin's settings.
        services: The core services.
        logger: The plugin's logger.
        data_dir: A folder only this plugin writes to; kept across updates and removed on uninstall.
        permissions: The permissions granted at install (the manifest's list).
        storage: The plugin's own records, available with storage.read or storage.write; otherwise None.
        secrets: The secrets vault, available with the secrets permission; otherwise None.
        mail: The mailer, available with mail.send; otherwise None.
        sudoo_version: The version of the panel. Default "2.0.0".
    """

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
        """The Caller for things the plugin does on its own (a background task, an instance hook).

        Limited to what the permissions granted at install allow (PLUGIN_GRANTS), audited as plugin:<id>.
        """
        return Caller(name=f"plugin:{self.plugin_id}", permissions=granted(self.permissions), via="plugin")

    def require(self, permission: str) -> None:
        """Raise PermissionError when the plugin was not granted `permission`; call before using a capability."""
        if permission not in self.permissions:
            raise PermissionError(f"{self.plugin_id} was not granted the permission {permission}.")
