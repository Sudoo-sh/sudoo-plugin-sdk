"""Interfaces of the plugin groups planned for the plugin manager of Sudoo.sh 2.0 (ROADMAP section 11).

These are the SDK's proposal for each contract. They may still change before SDK 1.0; a change is listed in the
CHANGELOG and checked by `sudoo-plugin validate` against the `sdk_version` your manifest names.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from sudoo_plugin_sdk.context import Caller, Resource

# --------------------------------------------------------------------------- sudoo.backups


@dataclass(frozen=True, slots=True)
class StoredBackup:
    name: str  # the backup's file name, e.g. sales-main__sales_main__20261112-000012__daily.zip
    size: int
    created_at: float  # Unix seconds


@runtime_checkable
class BackupDestination(Protocol):
    """Keeps copies of backups somewhere else (S3, SFTP). The panel still makes the backup; the destination
    stores, lists, fetches and deletes copies."""

    name: str  # "s3"
    label: str  # "Amazon S3 or compatible"

    def upload(self, local: Path, name: str) -> None: ...
    def list(self, prefix: str = "") -> list[StoredBackup]: ...
    def download(self, name: str, local: Path) -> None: ...
    def delete(self, name: str) -> bool: ...


# --------------------------------------------------------------------------- sudoo.notifications

Severity = Literal["info", "success", "warning", "error"]


@dataclass(frozen=True, slots=True)
class Notification:
    """One thing worth telling people about."""

    event: str  # "job.finished", "instance.created", "update.failed", "backup.created", ...
    title: str  # "Update of sales-main failed"
    text: str  # a sentence or two, plain text
    severity: Severity = "info"
    url: str | None = None  # where to look in the panel
    data: Mapping[str, Any] = field(default_factory=dict)  # the API resource concerned (never passwords)


@runtime_checkable
class NotificationChannel(Protocol):
    """Sends notifications to a channel (Slack, Discord, Teams, SMS)."""

    name: str  # "slack"
    label: str  # "Slack"
    events: frozenset[str]  # the events it wants; empty means all

    @property
    def ready(self) -> bool:
        """True when it is configured (a webhook address is set, ...)."""
        ...

    def send(self, notification: Notification) -> None:
        """Deliver it, or raise RuntimeError with a sentence saying why not. The panel retries later."""
        ...


# --------------------------------------------------------------------------- sudoo.instance_hooks

InstanceEvent = Literal["created", "started", "stopped", "updated", "restored", "deleting", "deleted"]


@runtime_checkable
class InstanceHook(Protocol):
    """Runs when something happens to an instance (installs Odoo modules, registers DNS, ...). Runs inside the
    job, so its output appears in the job's log; raising fails the step with that message."""

    events: frozenset[InstanceEvent]

    def handle(self, event: InstanceEvent, instance: Resource, log: Callable[[str], None]) -> None: ...


# --------------------------------------------------------------------------- sudoo.dashboard_widgets


@dataclass(frozen=True, slots=True)
class Widget:
    """A card on the dashboard: a figure with an optional line, or a short list."""

    title: str
    value: str | None = None  # "99.9%"
    caption: str | None = None  # "uptime, last 30 days"
    items: tuple[tuple[str, str], ...] = ()  # (label, value) rows
    url: str | None = None
    tone: Literal["neutral", "positive", "caution", "negative"] = "neutral"


@runtime_checkable
class DashboardWidget(Protocol):
    name: str
    refresh_seconds: int  # how often the panel asks again (at least 15)

    def render(self, caller: Caller) -> Widget | None:
        """The card for this person (None: nothing to show them)."""
        ...


# --------------------------------------------------------------------------- sudoo.web_pages


@dataclass(frozen=True, slots=True)
class PageInfo:
    path: str  # under /plugins/<id>/, e.g. "tokens"
    title: str  # "API tokens"
    permission: str | None  # who sees it in the sidebar
    bundle: str  # the pre-built JavaScript module in the package, e.g. "web/dist/Tokens.js"
    icon: str = "puzzle"  # a lucide icon name


@runtime_checkable
class WebPage(Protocol):
    def pages(self) -> list[PageInfo]: ...


# --------------------------------------------------------------------------- sudoo.background_tasks


@runtime_checkable
class BackgroundTask(Protocol):
    """Recurring work. The panel runs `run` every `interval_seconds` on its worker, never twice at once."""

    name: str
    interval_seconds: int

    def run(self, caller: Caller) -> None: ...


# --------------------------------------------------------------------------- sudoo.api_access, sudoo.api_blueprints


@dataclass(frozen=True, slots=True)
class ApiRequest:
    """A request as the core sees it, built for the Flask app and the asyncio server alike."""

    method: str
    path: str  # with the query
    headers: Mapping[str, str]
    body: bytes = b""
    client_ip: str = ""

    def header(self, name: str) -> str | None:
        lowered = name.lower()
        return next((value for key, value in self.headers.items() if key.lower() == lowered), None)


@dataclass(frozen=True, slots=True)
class ApiResponse:
    status: int = 200
    body: Any = None  # JSON-serialisable
    headers: Mapping[str, str] = field(default_factory=dict)


Handler = Callable[[ApiRequest, Caller], ApiResponse]


@dataclass(frozen=True, slots=True)
class Route:
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str  # "/api/v1/tokens", or relative to /api/v1/plugins/<id>/ for sudoo.api_blueprints
    permission: str | None
    handler: Handler
    summary: str = ""


class AccessRefused(Exception):
    """Refuse a request an ApiAccess plugin recognised (wrong signature, expired token)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@runtime_checkable
class ApiAccess(Protocol):
    """Authenticates callers that are not the browser app, and adds the routes that manage them."""

    name: str

    def authenticate(self, request: ApiRequest) -> Caller | None:
        """A Caller for a request this plugin recognises, None when the request is not for it. Raise
        AccessRefused(status, detail) to refuse; the core audits and throttles."""
        ...

    def routes(self) -> list[Route]: ...

    def permissions(self) -> dict[str, str]:
        """Permissions this plugin adds to the panel's roles, e.g. {"webhooks.manage": "Manage outbound webhooks"}."""
        ...


@runtime_checkable
class ApiRoutes(Protocol):
    """Extra endpoints under /api/v1/plugins/<id>/ (sudoo.api_blueprints)."""

    def routes(self) -> list[Route]: ...


# --------------------------------------------------------------------------- sudoo.mcp


@runtime_checkable
class McpServer(Protocol):
    """Serves the panel's operations at /mcp to Model Context Protocol clients. Every tool is a call to
    context.services with the caller's permissions."""

    def handle(self, request: ApiRequest, caller: Caller) -> ApiResponse | Iterator[bytes]: ...


# --------------------------------------------------------------------------- sudoo.extensions


@runtime_checkable
class Extension(Protocol):
    """Anything else: a plugin that only uses the lifecycle hooks of SudooPlugin and context.services."""

    def on_enable(self) -> None: ...
