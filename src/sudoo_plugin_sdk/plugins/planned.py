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
    """A backup copy kept by a destination.

    Attributes:
        name: The backup's file name, for example sales-main__sales_main__20261112-000012__daily.zip.
        size: The size in bytes.
        created_at: When it was made, in Unix seconds.
    """

    name: str  # the backup's file name, e.g. sales-main__sales_main__20261112-000012__daily.zip
    size: int
    created_at: float  # Unix seconds


@runtime_checkable
class BackupDestination(Protocol):
    """Keeps copies of backups somewhere else (S3, SFTP).

    The panel still makes the backup; the destination stores, lists, fetches and deletes copies.

    Attributes:
        name: The short name, for example "s3".
        label: The text shown to people, for example "Amazon S3 or compatible".
    """

    name: str  # "s3"
    label: str  # "Amazon S3 or compatible"

    def upload(self, local: Path, name: str) -> None:
        """Store a copy.

        Args:
            local: The local file to store.
            name: The name to store it under.
        """
        ...

    def list(self, prefix: str = "") -> list[StoredBackup]:
        """List the stored copies.

        Args:
            prefix: Only names that start with this text.

        Returns:
            The copies.
        """
        ...

    def download(self, name: str, local: Path) -> None:
        """Fetch a copy to a local file.

        Args:
            name: The copy's name.
            local: Where to write it.
        """
        ...

    def delete(self, name: str) -> bool:
        """Delete a copy.

        Args:
            name: The copy's name.

        Returns:
            True when there was a copy to delete.
        """
        ...


# --------------------------------------------------------------------------- sudoo.notifications

# How serious a notification is.
Severity = Literal["info", "success", "warning", "error"]


@dataclass(frozen=True, slots=True)
class Notification:
    """One thing worth telling people about.

    Attributes:
        event: What happened, for example "job.finished", "instance.created", "update.failed" or "backup.created".
        title: A short headline, for example "Update of sales-main failed".
        text: A sentence or two, as plain text.
        severity: "info" (default), "success", "warning" or "error".
        url: Where to look in the panel, or None.
        data: The API resource concerned, never with passwords.
    """

    event: str  # "job.finished", "instance.created", "update.failed", "backup.created", ...
    title: str  # "Update of sales-main failed"
    text: str  # a sentence or two, plain text
    severity: Severity = "info"
    url: str | None = None  # where to look in the panel
    data: Mapping[str, Any] = field(default_factory=dict)  # the API resource concerned (never passwords)


@runtime_checkable
class NotificationChannel(Protocol):
    """Sends notifications to a channel (Slack, Discord, Teams, SMS).

    Attributes:
        name: The short name, for example "slack".
        label: The text shown to people, for example "Slack".
        events: The events the channel wants; empty means all.
    """

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

# What can happen to an instance, as an instance hook sees it.
InstanceEvent = Literal["created", "started", "stopped", "updated", "restored", "deleting", "deleted"]


@runtime_checkable
class InstanceHook(Protocol):
    """Runs when something happens to an instance (installs Odoo modules, registers DNS, ...).

    It runs inside the job, so its output appears in the job's log; raising fails the step with that message.

    Attributes:
        events: The events the hook wants to be called for.
    """

    events: frozenset[InstanceEvent]

    def handle(self, event: InstanceEvent, instance: Resource, log: Callable[[str], None]) -> None:
        """Handle one event.

        Args:
            event: What happened.
            instance: The instance, as an API resource.
            log: Writes a line to the job's log.
        """
        ...


# --------------------------------------------------------------------------- sudoo.dashboard_widgets


@dataclass(frozen=True, slots=True)
class Widget:
    """A card on the dashboard: a figure with an optional line, or a short list.

    Attributes:
        title: The card's title.
        value: The main figure, for example "99.9%", or None.
        caption: A line under the figure, for example "uptime, last 30 days", or None.
        items: Rows of (label, value) pairs; empty by default.
        url: Where the card links to, or None.
        tone: "neutral" (default), "positive", "caution" or "negative".
    """

    title: str
    value: str | None = None  # "99.9%"
    caption: str | None = None  # "uptime, last 30 days"
    items: tuple[tuple[str, str], ...] = ()  # (label, value) rows
    url: str | None = None
    tone: Literal["neutral", "positive", "caution", "negative"] = "neutral"


@runtime_checkable
class DashboardWidget(Protocol):
    """Adds a card to the dashboard.

    Attributes:
        name: The widget's name.
        refresh_seconds: How often the panel asks again, in seconds (at least 15).
    """

    name: str
    refresh_seconds: int  # how often the panel asks again (at least 15)

    def render(self, caller: Caller) -> Widget | None:
        """The card for this person (None: nothing to show them)."""
        ...


# --------------------------------------------------------------------------- sudoo.web_pages


@dataclass(frozen=True, slots=True)
class PageInfo:
    """A page that a plugin adds to the web app.

    Attributes:
        path: The path under /plugins/<id>/, for example "tokens".
        title: The page's title, for example "API tokens".
        permission: The permission a person needs to see it in the sidebar, or None.
        bundle: The pre-built JavaScript module in the package, for example "web/dist/Tokens.js".
        icon: A lucide icon name. Default "puzzle".
    """

    path: str  # under /plugins/<id>/, e.g. "tokens"
    title: str  # "API tokens"
    permission: str | None  # who sees it in the sidebar
    bundle: str  # the pre-built JavaScript module in the package, e.g. "web/dist/Tokens.js"
    icon: str = "puzzle"  # a lucide icon name


@runtime_checkable
class WebPage(Protocol):
    """Adds pages to the web app."""

    def pages(self) -> list[PageInfo]:
        """List the pages.

        Returns:
            The pages.
        """
        ...


# --------------------------------------------------------------------------- sudoo.background_tasks


@runtime_checkable
class BackgroundTask(Protocol):
    """Recurring work. The panel runs `run` every `interval_seconds` on its worker, never twice at once.

    Attributes:
        name: The task's name.
        interval_seconds: Seconds between two runs.
    """

    name: str
    interval_seconds: int

    def run(self, caller: Caller) -> None:
        """Do the work once.

        Args:
            caller: The caller the work is done as.
        """
        ...


# --------------------------------------------------------------------------- sudoo.api_access, sudoo.api_blueprints


@dataclass(frozen=True, slots=True)
class ApiRequest:
    """A request as the core sees it, built for the Flask app and the asyncio server alike.

    Attributes:
        method: The HTTP method.
        path: The path, with the query string.
        headers: The request headers.
        body: The request body bytes; empty by default.
        client_ip: The caller's IP address; "" when unknown.
    """

    method: str
    path: str  # with the query
    headers: Mapping[str, str]
    body: bytes = b""
    client_ip: str = ""

    def header(self, name: str) -> str | None:
        """Read a header, ignoring the case of its name.

        Args:
            name: The header's name.

        Returns:
            The value, or None when the request has no such header.
        """
        lowered = name.lower()
        return next((value for key, value in self.headers.items() if key.lower() == lowered), None)


@dataclass(frozen=True, slots=True)
class ApiResponse:
    """An answer to an API request.

    Attributes:
        status: The HTTP status code. Default 200.
        body: The body, any value that can be written as JSON.
        headers: Extra response headers.
    """

    status: int = 200
    body: Any = None  # JSON-serialisable
    headers: Mapping[str, str] = field(default_factory=dict)


# A function that answers one API request: it takes the request and the caller and returns the response.
Handler = Callable[[ApiRequest, Caller], ApiResponse]


@dataclass(frozen=True, slots=True)
class Route:
    """An endpoint a plugin adds.

    Attributes:
        method: GET, POST, PUT, PATCH or DELETE.
        path: "/api/v1/tokens", or a path relative to /api/v1/plugins/<id>/ for sudoo.api_blueprints.
        permission: The permission a caller needs, or None.
        handler: The function that answers the request.
        summary: One line saying what the endpoint does; empty by default.
    """

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str  # "/api/v1/tokens", or relative to /api/v1/plugins/<id>/ for sudoo.api_blueprints
    permission: str | None
    handler: Handler
    summary: str = ""


class AccessRefused(Exception):
    """Refuse a request an ApiAccess plugin recognised (wrong signature, expired token).

    Attributes:
        status: The HTTP status code to answer with.
        detail: The text for the problem detail.
    """

    def __init__(self, status: int, detail: str) -> None:
        """Create the refusal.

        Args:
            status: The HTTP status code.
            detail: The text for the problem detail.
        """
        super().__init__(detail)
        self.status = status
        self.detail = detail


@runtime_checkable
class ApiAccess(Protocol):
    """Authenticates callers that are not the browser app, and adds the routes that manage them.

    Attributes:
        name: The plugin's name.
    """

    name: str

    def authenticate(self, request: ApiRequest) -> Caller | None:
        """A Caller for a request this plugin recognises, None when the request is not for it.

        Raise AccessRefused(status, detail) to refuse; the core audits and throttles.
        """
        ...

    def routes(self) -> list[Route]:
        """List the routes this plugin adds, for example the ones that manage tokens.

        Returns:
            The routes.
        """
        ...

    def permissions(self) -> dict[str, str]:
        """Permissions this plugin adds to the panel's roles, e.g. {"webhooks.manage": "Manage outbound webhooks"}."""
        ...


@runtime_checkable
class ApiRoutes(Protocol):
    """Extra endpoints under /api/v1/plugins/<id>/ (sudoo.api_blueprints)."""

    def routes(self) -> list[Route]:
        """List the endpoints.

        Returns:
            The routes.
        """
        ...


# --------------------------------------------------------------------------- sudoo.mcp


@runtime_checkable
class McpServer(Protocol):
    """Serves the panel's operations at /mcp to Model Context Protocol clients.

    Every tool is a call to context.services with the caller's permissions.
    """

    def handle(self, request: ApiRequest, caller: Caller) -> ApiResponse | Iterator[bytes]:
        """Answer one request.

        Args:
            request: The request.
            caller: Who is calling.

        Returns:
            A response, or a stream of byte chunks for a streaming answer.
        """
        ...


# --------------------------------------------------------------------------- sudoo.extensions


@runtime_checkable
class Extension(Protocol):
    """Anything else: a plugin that only uses the lifecycle hooks of SudooPlugin and context.services."""

    def on_enable(self) -> None:
        """Called when the administrator turns the plugin on."""
        ...
