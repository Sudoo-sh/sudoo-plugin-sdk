"""`sudoo-plugin publish`: send a package to the hub's developer endpoint (what developers.sudoo.sh uses).

    POST {hub}/api/v1/developer/plugins                       a new plugin with its first version
    POST {hub}/api/v1/developer/plugins/{id}/versions         a new version (or the same one after changes were asked)

multipart/form-data with `manifest` (manifest.json), `package` (the .sudoo file) and `changelog` (what changed).
The token is sent as `Authorization: Bearer <token>` and comes from the environment (SUDOO_DEVELOPER_TOKEN), never
from an argument, so it does not end up in shell history or CI logs.

A developer API token (`sdk_...`, made on developers.sudoo.sh for CI) can do one thing: submit new versions of the
developer's own plugins. With one, publish sends straight to the versions endpoint; a plugin's first version is
submitted from developers.sudoo.sh. Other tokens list the developer's plugins first to choose the endpoint. The hub answers with the version's state and
the results of its automated checks; a person then reviews it (free plugins from verified publishers may skip the
review for patch versions).
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from sudoo_plugin_sdk import __version__
from sudoo_plugin_sdk.manifest import MANIFEST_NAME
from sudoo_plugin_sdk.package import read_manifest
from sudoo_plugin_sdk.signing import sha256_of

# The address of the hub that is used when none is given.
DEFAULT_HUB = "https://hub.sudoo.sh"
# The environment variable that holds the developer token.
TOKEN_ENV = "SUDOO_DEVELOPER_TOKEN"  # noqa: S105 - the name of the variable, not a secret
# The environment variable that holds the hub's address.
HUB_ENV = "SUDOO_HUB_URL"
# The start of a developer API token.
API_TOKEN_PREFIX = "sdk_"  # noqa: S105 - the prefix of developer API tokens, not a secret
# The longest changelog text accepted, in characters.
MAX_CHANGELOG = 10_000


class PublishError(RuntimeError):
    """Publishing failed; the message says why."""

    pass


@dataclass(frozen=True)
class Submission:
    """The result of a submission.

    Attributes:
        url: The hub's address.
        plugin_id: The plugin's id.
        version: The version submitted.
        sha256: The package's SHA-256, as hex.
        size: The package's size in bytes.
        new_plugin: True for a first version, False for a later one, None in a dry run (the hub was not asked).
        response: The hub's answer, or None in a dry run.
    """

    url: str
    plugin_id: str
    version: str
    sha256: str
    size: int
    new_plugin: bool | None  # None in a dry run (the hub was not asked)
    response: dict[str, Any] | None


def hub_url(value: str | None) -> str:
    """Pick and check the hub's address.

    Args:
        value: The address given, or None to use SUDOO_HUB_URL or the default.

    Returns:
        The address without a trailing slash.

    Raises:
        PublishError: When it is not https (http is allowed only for a hub on this computer).
    """
    url = (value or os.environ.get(HUB_ENV) or DEFAULT_HUB).rstrip("/")
    parts = urlsplit(url)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1") or (parts.hostname or "").endswith(".localhost")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise PublishError(f"{url} must be an https:// address (http only for a hub on this computer).")
    return url


def changelog_entry(project: Path, version: str) -> str | None:
    """The section of CHANGELOG.md for `version` ("## 1.2.0" or "## [1.2.0] - date"), without its heading.

    Args:
        project: The plugin's folder.
        version: The version to look for.

    Returns:
        The section's text, or None when there is no file, no such section or the section is empty.
    """
    path = project / "CHANGELOG.md"
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    heading = re.compile(rf"^##\s+\[?v?{re.escape(version)}\]?(\s|$)")
    for index, line in enumerate(lines):
        if heading.match(line):
            body: list[str] = []
            for following in lines[index + 1 :]:
                if following.startswith("## "):
                    break
                body.append(following)
            text = "\n".join(body).strip()
            return text or None
    return None


def publish(
    package: Path,
    changelog: str,
    *,
    hub: str | None = None,
    token: str | None = None,
    dry_run: bool = False,
    client: httpx.Client | None = None,
) -> Submission:
    """Send a package to the hub.

    With `dry_run` nothing is sent. Without a token given, it is read from SUDOO_DEVELOPER_TOKEN. A token that starts
    with "sdk_" submits versions only; any other token first lists the developer's plugins to choose the endpoint.

    Args:
        package: The .sudoo file.
        changelog: What changed in this version, 1 to 10,000 characters.
        hub: The hub's address, or None.
        token: The developer token, or None to read it from the environment.
        dry_run: When True, only read the package and return what would be sent.
        client: An HTTP client to use, or None to make one.

    Returns:
        The submission, with the hub's answer.

    Raises:
        PublishError: When the package, the changelog, the token or the hub's answer is not acceptable, or the hub
            cannot be reached.

    Side effects:
        Network calls to the hub.
    """
    url = hub_url(hub)
    data = package.read_bytes()
    try:
        manifest = read_manifest(data)
    except ValueError as error:
        raise PublishError(str(error)) from None
    changelog = changelog.strip()
    if not changelog or len(changelog) > MAX_CHANGELOG:
        raise PublishError(f"Say what changed in this version (1 to {MAX_CHANGELOG} characters).")
    sha256 = sha256_of(data)
    if dry_run:
        return Submission(url, manifest.id, manifest.version, sha256, len(data), None, None)
    token = token if token is not None else os.environ.get(TOKEN_ENV, "")
    if not token.strip():
        raise PublishError(f"Set {TOKEN_ENV} to your developer token (developers.sudoo.sh, Settings).")
    headers = {"Authorization": f"Bearer {token.strip()}", "User-Agent": f"sudoo-plugin/{__version__}"}
    own_client = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0), follow_redirects=False)
    try:
        if token.strip().startswith(API_TOKEN_PREFIX):
            new_plugin = False  # an API token submits versions only
        else:
            listing = http.get(f"{url}/api/v1/developer/plugins", headers=headers)
            _raise_for(listing)
            known = {item.get("id") for item in listing.json().get("data", [])}
            new_plugin = manifest.id not in known
        endpoint = (
            f"{url}/api/v1/developer/plugins"
            if new_plugin
            else f"{url}/api/v1/developer/plugins/{manifest.id}/versions"
        )
        response = http.post(
            endpoint,
            headers=headers,
            data={"changelog": changelog},
            files={
                "manifest": (MANIFEST_NAME, manifest_bytes(data), "application/json"),
                "package": (package.name, data, "application/zip"),
            },
        )
        if response.status_code == 404 and not new_plugin:
            raise PublishError(
                f"{manifest.id} is not one of your plugins on {url}. Submit its first version on "
                "developers.sudoo.sh (Plugins, New plugin); publish then sends the versions after it."
            )
        _raise_for(response)
        body: dict[str, Any] = response.json()
    except httpx.HTTPError as error:
        raise PublishError(f"The hub at {url} could not be reached: {error}") from None
    finally:
        if own_client:
            http.close()
    return Submission(url, manifest.id, manifest.version, sha256, len(data), new_plugin, body)


def manifest_bytes(package: bytes) -> bytes:
    """manifest.json exactly as it is in the package (the hub compares the two).

    Args:
        package: The package bytes.

    Returns:
        The manifest's bytes.
    """
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        return archive.read(MANIFEST_NAME)


def _raise_for(response: httpx.Response) -> None:
    """Turn an error answer of the hub into a `PublishError` with the hub's message and the fields it names.

    Args:
        response: The hub's answer. Nothing happens when its status is below 400.

    Raises:
        PublishError: When the status is 400 or higher.
    """
    if response.status_code < 400:
        return
    try:
        problem = response.json()
    except ValueError:
        problem = {}
    message = problem.get("detail") or problem.get("title") or response.reason_phrase
    errors = problem.get("errors") or []
    lines = [f"The hub refused the request ({response.status_code}): {message}"]
    lines += [f"  {item.get('field', '')}: {item.get('message', '')}" for item in errors if isinstance(item, dict)]
    if response.status_code == 401:
        lines.append(f"  Check {TOKEN_ENV}: it is missing, wrong, expired or revoked.")
    if response.status_code == 403 and problem.get("code") == "token_scope":
        lines.append("  A developer API token can only submit new versions of your own plugins.")
    raise PublishError("\n".join(lines))
