"""The eight plugin interfaces the panel loads today (src/sudoo/*/base.py in the panel), without Flask types.

They mirror the panel's Protocols method for method, so a class written against them works in the panel. The
panel creates the class once; under the plugin manager of Sudoo.sh 2.0 it passes a PluginContext (subclass
SudooPlugin), the built-in plugins of earlier versions receive the panel's Settings object instead.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# A function that takes one line of text and writes it to the log of the current job.
Log = Callable[[str], None]
# An account record of the panel, as a dictionary.
Account = dict[str, Any]
# A record kept by a storage plugin, as a dictionary.
Document = dict[str, Any]


# --------------------------------------------------------------------------- sudoo.exposure


@dataclass(frozen=True)
class Target:
    """Something to expose: the panel (name "panel") or an instance, and the local port it listens on.

    Attributes:
        name: "panel" for the panel itself, else the instance's name.
        port: The local port it listens on.
        env: The instance's .env values (empty for the panel).
    """

    name: str
    port: int
    env: Mapping[str, str] = field(default_factory=dict)  # the instance's .env (empty for the panel)


@runtime_checkable
class Exposure(Protocol):
    """How a local port becomes a public address (sudoo.exposure).

    Attributes:
        listen_host: 127.0.0.1 when a connector reaches the ports locally, 0.0.0.0 when visitors connect directly.
        https: True when visitors use https, so cookies can be marked Secure.
        client_ip_header: A header carrying the visitor's real address that only the service in front can set, or None.
    """

    listen_host: str
    """127.0.0.1 when a connector reaches the ports locally, 0.0.0.0 when visitors connect directly."""
    https: bool
    """True when visitors use https, so cookies can be marked Secure."""
    client_ip_header: str | None
    """A header carrying the visitor's real address that only the service in front can set, or None."""

    def instance_ports(self) -> dict[str, int]:
        """Extra ports needed per instance, as {.env key: first port}."""
        ...

    def panel_env(self) -> dict[str, str]:
        """Values needed for the panel's own target."""
        ...

    def ensure(self, target: Target) -> None:
        """Make the target reachable; does nothing when it already is (called again and again)."""
        ...

    def remove(self, target: Target) -> None:
        """Stop exposing the target."""
        ...

    def address(self, target: Target) -> str | None:
        """The public address, or None while it is not ready."""
        ...


# --------------------------------------------------------------------------- sudoo.addon_sources


@runtime_checkable
class AddonSource(Protocol):
    """Provides the Odoo Enterprise add-ons of each version (sudoo.addon_sources)."""

    def available(self, version: str) -> bool:
        """True when the add-ons of `version` can be used (now, or after prepare())."""
        ...

    def prepare(self, version: str, log: Log) -> Path:
        """Make the add-ons of `version` ready on this server and return their folder (on the host)."""
        ...


# --------------------------------------------------------------------------- sudoo.update_triggers

# A function request_update(instance name, reason) that asks the panel to update that instance.
RequestUpdate = Callable[[str, str], None]
"""request_update(instance name, reason): ask the panel to update that instance."""


@runtime_checkable
class UpdateTrigger(Protocol):
    """Notices new code and asks the panel to update the instances concerned (sudoo.update_triggers)."""

    def start(self, request_update: RequestUpdate) -> None:
        """Begin watching; called once when the panel starts."""
        ...

    def blueprint(self) -> Any | None:
        """A Flask Blueprint with the endpoints the trigger needs (served under /hooks/), or None.

        Webhooks must check their sender's signature themselves.
        """
        ...


# --------------------------------------------------------------------------- sudoo.storage


@runtime_checkable
class Storage(Protocol):
    """Where the panel keeps its own data (sudoo.storage)."""

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
        """Write one record, replacing any record with the same key.

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
        """Change one record in a single step.

        Args:
            collection: The collection's name.
            key: The record's key.
            fn: Called with the current record (None when there is none). It returns the new record, or None.

        Returns:
            The record after the change, or None.
        """
        ...

    def log(self, entry: Document) -> None:
        """Add an entry to the audit log.

        Args:
            entry: The entry.
        """
        ...

    def logs(
        self, limit: int = 200, offset: int = 0, user: str | None = None, instance: str | None = None
    ) -> list[Document]:
        """Read audit log entries.

        Args:
            limit: The most entries to return.
            offset: How many entries to skip.
            user: Only entries of this user, or None for all.
            instance: Only entries about this instance, or None for all.

        Returns:
            The entries.
        """
        ...


# --------------------------------------------------------------------------- sudoo.auth, sudoo.second_factors


@dataclass(frozen=True, slots=True)
class RequestInfo:
    """Where a sign-in or setup came from, shown in e-mails so people recognise attempts that were not theirs.

    Attributes:
        ip: The visitor's IP address, "" when unknown.
        user_agent: The visitor's browser or client description, "" when unknown.
        at: Unix time in seconds of the attempt; 0.0 when unknown.
    """

    ip: str = ""
    user_agent: str = ""
    at: float = 0.0


@dataclass(frozen=True, slots=True)
class Identity:
    """Who signed in, as an authenticator reports it.

    Attributes:
        username: The account name.
        role: The panel role to give the account. Used only when the account is created on first sign-in. Default
            "viewer".
        email: The account's e-mail address, or None.
    """

    username: str
    role: str = "viewer"  # used only when the account is created on first sign-in
    email: str | None = None


@runtime_checkable
class Authenticator(Protocol):
    """Checks a user name and password (sudoo.auth).

    Attributes:
        manages_passwords: True when passwords are set in the panel (Change password and Reset password are offered).
    """

    manages_passwords: bool
    """True when passwords are set in the panel (Change password, Reset password are offered)."""

    def authenticate(self, username: str, password: str) -> Identity | None:
        """The identity when the password is right, else None. Must take as long for unknown users."""
        ...


@runtime_checkable
class SecondFactor(Protocol):
    """Proves it is really that person after the password (sudoo.second_factors).

    Attributes:
        name: The short name, "email", "totp" or "sms".
        label: The text shown to people, such as "E-mail code" or "Authenticator app".
    """

    name: str  # "email", "totp", "sms"
    label: str  # shown to people: "E-mail code", "Authenticator app"

    @property
    def available(self) -> bool:
        """Whether this second factor can be used now.

        Returns:
            True when it is configured and ready.
        """
        ...

    def enrolled(self, account: Account) -> bool:
        """Tell whether an account has set this second factor up.

        Args:
            account: The account record.

        Returns:
            True when it has.
        """
        ...

    def challenge(self, username: str, account: Account, origin: RequestInfo) -> dict[str, Any]:
        """Start the check at sign-in.

        Args:
            username: The account name.
            account: The account record.
            origin: Where the sign-in came from.

        Returns:
            A dict with details of the challenge.
        """
        ...

    def verify(self, username: str, account: Account, code: str) -> bool:
        """Check the code a person typed.

        Args:
            username: The account name.
            account: The account record.
            code: The code.

        Returns:
            True when the code is right.
        """
        ...

    def begin_setup(
        self, username: str, account: Account, details: dict[str, Any], origin: RequestInfo
    ) -> dict[str, Any]:
        """Start setting this second factor up for an account.

        Args:
            username: The account name.
            account: The account record.
            details: What the person entered for the setup (for example a phone number).
            origin: Where the setup came from.

        Returns:
            A dict with details of the setup.
        """
        ...

    def finish_setup(self, username: str, account: Account, code: str) -> dict[str, Any] | None:
        """Finish the setup with the code the person typed.

        Args:
            username: The account name.
            account: The account record.
            code: The code.

        Returns:
            A dict with data about the finished setup, or None when it did not finish.
        """
        ...

    def remove(self, account: Account) -> dict[str, Any]:
        """Take this second factor away from an account.

        Args:
            account: The account record.

        Returns:
            A dict with data about the result.
        """
        ...


# --------------------------------------------------------------------------- sudoo.mailers


class MailError(RuntimeError):
    """The message could not be sent; the text says why, for the person who asked for it."""


@runtime_checkable
class Mailer(Protocol):
    """How the panel sends e-mail (sudoo.mailers)."""

    @property
    def ready(self) -> bool:
        """True when it is configured and can send."""
        ...

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        """Send one message, or raise MailError."""
        ...


# --------------------------------------------------------------------------- sudoo.rate_limiters


@dataclass(frozen=True, slots=True)
class Decision:
    """The answer of a rate limiter.

    Attributes:
        allowed: True when the request may go on.
        limit: The most requests allowed in the window.
        remaining: How many are left in the window.
        reset_seconds: Seconds until the window resets.
    """

    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int


@runtime_checkable
class RateLimiter(Protocol):
    """Where request counts are kept (sudoo.rate_limiters)."""

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> Decision:
        """Count one request for a key.

        Args:
            key: What is being limited, for example an IP address.
            limit: The most requests allowed in the window.
            window_seconds: The length of the window, in seconds.

        Returns:
            The decision for this request.
        """
        ...
