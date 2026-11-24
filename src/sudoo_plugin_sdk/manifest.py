"""The plugin manifest (manifest.json), version 1.

A port of the hub's own model (hub.sudoo.sh validates every submitted manifest with the same rules), so a manifest
that passes here passes there. Its JSON Schema is served at https://hub.sudoo.sh/schemas/plugin-manifest-v1.json,
the `$schema` a manifest names, and `sudoo-plugin schema` prints this copy. Unknown fields are refused, so a typo
cannot silently drop a setting or a permission.

Keep this module in step with the hub: tests/test_manifest.py mirrors the hub's test cases.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

# The address of the manifest's JSON Schema on the hub.
SCHEMA_URL = "https://hub.sudoo.sh/schemas/plugin-manifest-v1.json"

# semver 2.0.0 (https://semver.org), without a leading "v"
# Regular expression text for a semantic version (semver 2.0.0, https://semver.org), without a leading "v".
SEMVER = (
    r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
)
# Compiled pattern of a whole semantic version.
SEMVER_RE = re.compile(rf"^{SEMVER}$")
# Compiled pattern of a version specifier: one or more clauses such as ">=1.0.0" joined by commas.
SPECIFIER_RE = re.compile(rf"^(?:(?:>=|<=|==|!=|~=|>|<)\s*{SEMVER})(?:\s*,\s*(?:>=|<=|==|!=|~=|>|<)\s*{SEMVER})*$")
# Pattern of a plugin id: lower-case words in 3 to 7 dot-separated parts, for example com.sudoo.smtp.
PLUGIN_ID = r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*(?:\.[a-z][a-z0-9]*(?:-[a-z0-9]+)*){2,6}$"  # com.sudoo.smtp
# Compiled pattern of an entry point target: module.path:Object.
ENTRY_POINT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_.]*$")
# Compiled pattern of an entry point group name: sudoo.<name>.
GROUP_RE = re.compile(r"^sudoo\.[a-z][a-z0-9_]{1,40}$")
# Compiled pattern of an entry point name.
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")
# Compiled pattern of an SPDX licence expression such as MIT or Apache-2.0.
SPDX_RE = re.compile(r"^[A-Za-z0-9.+-]{1,64}(?: (?:AND|OR|WITH) [A-Za-z0-9.+-]{1,64})*$")

# A plugin id: text that matches `PLUGIN_ID`, at most 128 characters.
PluginId = Annotated[str, StringConstraints(pattern=PLUGIN_ID, max_length=128)]
# A semantic version, at most 64 characters.
SemVer = Annotated[str, StringConstraints(pattern=rf"^{SEMVER}$", max_length=64)]
# A tag: lower-case letters, digits and "-", 1 to 31 characters, starting with a letter or digit.
Tag = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,30}$")]
# A trimmed text of 1 to 200 characters.
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# A setting key: a lower-case letter, then lower-case letters, digits or "_", at most 64 characters.
SettingKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]

# One type per panel entry-point group (sudoo.<group>, singular here), and the catch-all "extension".
# The kinds of plugin: one per panel entry-point group (sudoo.<group>, singular here), and the catch-all "extension".
PluginType = Literal[
    "auth",
    "second_factor",
    "mailer",
    "exposure",
    "update_trigger",
    "addon_source",
    "storage",
    "rate_limiter",
    "backup",
    "notification",
    "instance_hook",
    "dashboard_widget",
    "web_page",
    "background_task",
    "theme",
    "api",  # sudoo.api_access: the panel's REST API for other systems (tokens with signed requests, webhooks)
    "mcp",  # sudoo.mcp: a Model Context Protocol server, so MCP clients drive the panel within a token's rights
    "extension",
]
# The canonical permission ids. A plugin asks for each one it needs; the panel shows them before installing, and
# reviewers check that each is needed.
# The canonical permission ids with what each means.
#
# A plugin asks for each one it needs; the panel shows them before installing, and reviewers check that each is
# needed.
PERMISSION_DESCRIPTIONS: dict[str, str] = {
    "network.inbound": "Adds routes or endpoints that clients call on the panel",
    "network.outbound": "Makes network connections from the panel to other hosts",
    "instances.read": "Reads instances, their backups, jobs and logs",
    "instances.write": "Creates, restores, starts, stops and changes instances",
    "accounts.read": "Reads panel accounts and their roles",
    "settings.read": "Reads panel settings",
    "settings.write": "Changes panel settings",
    "storage.read": "Reads the plugin's own records",
    "storage.write": "Writes the plugin's own records",
    "filesystem.read": "Reads files on the server outside the plugin's records",
    "filesystem.write": "Writes files on the server outside the plugin's records",
    "secrets": "Keeps secrets in the panel's encrypted vault",
    "mail.send": "Sends e-mail through the panel's mailer",
    "docker": "Starts and removes containers (powerful: close to full control of the server)",
}
# The permission ids a manifest may list.
Permission = Literal[
    "network.inbound",
    "network.outbound",
    "instances.read",
    "instances.write",
    "accounts.read",
    "settings.read",
    "settings.write",
    "storage.read",
    "storage.write",
    "filesystem.read",
    "filesystem.write",
    "secrets",
    "mail.send",
    "docker",
]
# The plugin types, as a tuple of text.
PLUGIN_TYPES: tuple[str, ...] = get_args(PluginType)
# The permission ids, as a tuple of text.
PERMISSIONS: tuple[str, ...] = get_args(Permission)
assert set(PERMISSIONS) == set(PERMISSION_DESCRIPTIONS)  # noqa: S101 - one list, described once


def _relative_path(value: str) -> str:
    """A path inside the package: relative, forward slashes, no "..", no hidden tricks.

    Args:
        value: The path to check.

    Returns:
        The same path.

    Raises:
        ValueError: When it is empty, longer than 200 characters, starts with "/", has a backslash, an empty, "." or
            ".." part, or a control character.
    """
    parts = value.split("/")
    if (
        not value
        or len(value) > 200
        or value.startswith("/")
        or "\\" in value
        or any(part in ("", ".", "..") for part in parts)
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("must be a relative path inside the package (no leading /, no .., forward slashes)")
    return value


# A text of at most 200 characters that holds a path inside the package.
RelativePath = Annotated[str, Field(max_length=200)]


# Not a docstring: pydantic would copy a class docstring into the JSON Schema served by the hub.
# Who wrote the plugin.
#
# Attributes:
#     name: The author's name.
#     org: The organisation, or None.
#     email: An e-mail address, or None.
#     url: A web address, or None.
class Author(BaseModel):  # noqa: D101
    model_config = ConfigDict(extra="forbid")

    name: Text
    org: Text | None = None
    email: EmailStr | None = None
    url: AnyHttpUrl | None = None


# Attributes are listed here and not in the docstring: the docstring is part of the JSON Schema served by the hub.
#
# Attributes:
#     key: The setting's key.
# type: "string", "integer", "number", "boolean", "secret" or "choice".
#     label: The text shown next to the field.
#     description: Longer help text of at most 500 characters, or None.
#     default: The starting value. Its type must fit `type`; a secret has none; None means no default.
#     choices: The allowed values of a choice setting (up to 50, each up to 100 characters); None for other types.
#     editable: Whether the administrator can change it. Default True.
class Setting(BaseModel):
    """One setting the plugin adds to the panel's settings page."""

    model_config = ConfigDict(extra="forbid")

    key: SettingKey
    type: Literal["string", "integer", "number", "boolean", "secret", "choice"]
    label: Text
    description: Annotated[str, StringConstraints(max_length=500)] | None = None
    default: str | int | float | bool | None = None
    choices: list[Annotated[str, StringConstraints(max_length=100)]] | None = Field(default=None, max_length=50)
    editable: bool = True

    @model_validator(mode="after")
    def _default_matches_type(self) -> Setting:
        """Check that the choices and the default fit the setting's type.

        Returns:
            The setting itself.

        Raises:
            ValueError: When a choice setting has no choices, another type has choices, the default is not one of the
                choices, the default does not match the type, or a secret has a default.
        """
        value = self.default
        if self.type == "choice":
            if not self.choices:
                raise ValueError("a choice setting needs choices")
            if value is not None and value not in self.choices:
                raise ValueError("the default must be one of the choices")
        elif self.choices is not None:
            raise ValueError("only choice settings have choices")
        if value is None:
            return self
        expected: dict[str, tuple[type, ...]] = {
            "string": (str,),
            "secret": (str,),
            "choice": (str,),
            "integer": (int,),
            "number": (int, float),
            "boolean": (bool,),
        }
        wrong_bool = isinstance(value, bool) and self.type != "boolean"
        if wrong_bool or not isinstance(value, expected[self.type]):
            raise ValueError(f"the default does not match the type {self.type}")
        if self.type == "secret" and value != "":
            raise ValueError("a secret setting cannot have a default value")
        return self


# Attributes are listed here and not in the docstring: the docstring is part of the JSON Schema served by the hub.
#
# Attributes:
#     id: The other plugin's id.
#     version: A version specifier, or None for any version.
class Requirement(BaseModel):
    """Another plugin this one needs, with the versions it works with: {"id": "com.sudoo.api", "version":
    ">=1.0.0,<2.0.0"}. A bare id ("com.sudoo.api") means any version."""  # noqa: D205, D209

    model_config = ConfigDict(extra="forbid")

    id: PluginId
    version: Annotated[str, StringConstraints(max_length=100)] | None = None

    @model_validator(mode="before")
    @classmethod
    def _bare_id(cls, value: Any) -> Any:
        """Turn a bare id text into the object form.

        Args:
            value: The raw value.

        Returns:
            {"id": value} when the value is text, else the value unchanged.
        """
        return {"id": value} if isinstance(value, str) else value

    @field_validator("version")
    @classmethod
    def _specifier(cls, value: str | None) -> str | None:
        """Check the version specifier.

        Args:
            value: The specifier, or None.

        Returns:
            The specifier without surrounding spaces, or None.

        Raises:
            ValueError: When it is not a version specifier.
        """
        if value is None:
            return None
        if not SPECIFIER_RE.fullmatch(value.strip()):
            raise ValueError("must be a version specifier such as >=1.0.0 or >=1.0.0,<2.0.0")
        return value.strip()


# Not a docstring: pydantic would copy a class docstring into the JSON Schema served by the hub.
# The manifest of a plugin (manifest.json, version 1).
#
# Attributes:
#     schema_url: The "$schema" the manifest names, or None.
#     id: The plugin's id.
#     name: The plugin's name, 2 to 80 characters.
#     version: The plugin's version.
#     sdk_version: The versions of this SDK the plugin works with, as a version specifier.
#     min_sudoo_version: The lowest Sudoo.sh version it works with.
#     max_sudoo_version: The highest Sudoo.sh version it works with, or None.
#     author: Who wrote it.
#     description: A short description, 10 to 300 characters.
#     long_description_file: Path in the package of a longer description, or None.
#     license: An SPDX licence expression.
# type: The kind of plugin.
#     tags: Up to 10 tags, no repeats.
#     entry_points: The entry points by group: {group: {name: "module.path:Object"}}. At least one group.
#     settings: The settings the plugin adds, up to 100, with unique keys.
#     permissions: The permissions it asks for, no repeats.
#     requires: Other plugins it needs, up to 20, no repeats, never itself.
#     tier: "free" (default) or "paid".
#     price: The price in cents (100 to 1,000,000). Required for "paid" and not allowed for "free".
#     icon: Path in the package of the icon, or None.
#     screenshots: Paths in the package of up to 10 screenshots.
#     homepage: An https address, or None.
#     issues: An https address for bug reports, or None.
#     signature: Always None here: signatures travel next to the package, never inside the manifest it covers.
class Manifest(BaseModel):  # noqa: D101
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_url: Literal["https://hub.sudoo.sh/schemas/plugin-manifest-v1.json"] | None = Field(
        default=None, alias="$schema"
    )
    id: PluginId
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
    version: SemVer
    sdk_version: Annotated[str, StringConstraints(max_length=100)]
    min_sudoo_version: SemVer
    max_sudoo_version: SemVer | None = None
    author: Author
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=300)]
    long_description_file: RelativePath | None = None
    license: Annotated[str, StringConstraints(max_length=200)]
    type: PluginType
    tags: list[Tag] = Field(default_factory=list, max_length=10)
    entry_points: dict[str, dict[str, str]] = Field(min_length=1)
    settings: list[Setting] = Field(default_factory=list, max_length=100)
    permissions: list[Permission] = Field(default_factory=list)
    requires: list[Requirement] = Field(default_factory=list, max_length=20)
    tier: Literal["free", "paid"] = "free"
    price: Annotated[int, Field(ge=100, le=1_000_000)] | None = None  # cents
    icon: RelativePath | None = None
    screenshots: list[RelativePath] = Field(default_factory=list, max_length=10)
    homepage: AnyHttpUrl | None = None
    issues: AnyHttpUrl | None = None
    signature: None = None  # signatures travel next to the package, never inside the manifest it covers

    @field_validator("sdk_version")
    @classmethod
    def _specifier(cls, value: str) -> str:
        """Check the SDK version specifier.

        Args:
            value: The specifier.

        Returns:
            The specifier without surrounding spaces.

        Raises:
            ValueError: When it is not a version specifier.
        """
        if not SPECIFIER_RE.fullmatch(value.strip()):
            raise ValueError("must be a version specifier such as >=2.0.0 or >=2.0.0,<3.0.0")
        return value.strip()

    @field_validator("license")
    @classmethod
    def _license(cls, value: str) -> str:
        """Check the licence expression.

        Args:
            value: The expression.

        Returns:
            The same expression.

        Raises:
            ValueError: When it is not an SPDX expression.
        """
        if not SPDX_RE.fullmatch(value):
            raise ValueError("must be an SPDX license expression such as MIT or Apache-2.0")
        return value

    @field_validator("long_description_file", "icon")
    @classmethod
    def _path(cls, value: str | None) -> str | None:
        """Check a path field.

        Args:
            value: A path, or None.

        Returns:
            The same path, or None.
        """
        return None if value is None else _relative_path(value)

    @field_validator("screenshots")
    @classmethod
    def _paths(cls, value: list[str]) -> list[str]:
        """Check a list of path fields.

        Args:
            value: The paths.

        Returns:
            The same paths.
        """
        return [_relative_path(item) for item in value]

    @field_validator("tags", "permissions")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        """Check that a list has no repeated item.

        Args:
            value: The list.

        Returns:
            The same list.

        Raises:
            ValueError: When an item is repeated.
        """
        if len(set(value)) != len(value):
            raise ValueError("must not repeat an item")
        return value

    @field_validator("homepage", "issues")
    @classmethod
    def _https(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        """Check that an address uses https.

        Args:
            value: The address, or None.

        Returns:
            The same address, or None.

        Raises:
            ValueError: When the address does not start with https://.
        """
        if value is not None and value.scheme != "https":
            raise ValueError("must be an https:// address")
        return value

    @field_validator("entry_points")
    @classmethod
    def _entry_points(cls, value: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        """Check the group names, entry point names and targets.

        Args:
            value: The entry points by group.

        Returns:
            The same entry points.

        Raises:
            ValueError: When a group name is not sudoo.<name>, a group is empty, a name is not allowed or a target is not
                module.path:Object.
        """
        for group, entries in value.items():
            if not GROUP_RE.fullmatch(group):
                raise ValueError(f"entry point group {group!r} must look like sudoo.<name>")
            if not entries:
                raise ValueError(f"entry point group {group!r} is empty")
            for name, target in entries.items():
                if not NAME_RE.fullmatch(name):
                    raise ValueError(f"entry point name {name!r} must be lower case letters, digits, - and _")
                if not ENTRY_POINT_RE.fullmatch(target):
                    raise ValueError(f"entry point {name!r} must be module.path:Object")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> Manifest:
        """Check rules that involve several fields.

        Returns:
            The manifest itself.

        Raises:
            ValueError: When a paid plugin has no price, a free plugin has one, setting keys or required plugins repeat, a
                plugin requires itself, or max_sudoo_version is lower than min_sudoo_version.
        """
        if self.tier == "paid" and self.price is None:
            raise ValueError("a paid plugin needs a price (in cents)")
        if self.tier == "free" and self.price is not None:
            raise ValueError("a free plugin has no price")
        keys = [setting.key for setting in self.settings]
        if len(set(keys)) != len(keys):
            raise ValueError("setting keys must be unique")
        required = [requirement.id for requirement in self.requires]
        if len(set(required)) != len(required):
            raise ValueError("requires must not name a plugin twice")
        if self.id in required:
            raise ValueError("a plugin cannot require itself")
        if self.max_sudoo_version is not None and _semver_key(self.max_sudoo_version) < _semver_key(
            self.min_sudoo_version
        ):
            raise ValueError("max_sudoo_version is lower than min_sudoo_version")
        return self


def _semver_key(version: str) -> tuple[int, int, int, int, tuple[Any, ...]]:
    """Order of two semver versions (build metadata ignored; a pre-release sorts before its release).

    Args:
        version: A semantic version.

    Returns:
        A tuple that can be compared with another one.

    Raises:
        ValueError: When the text is not a semantic version.
    """
    match = SEMVER_RE.fullmatch(version)
    if match is None:
        raise ValueError(f"{version!r} is not a semver version")
    major, minor, patch, pre = int(match[1]), int(match[2]), int(match[3]), match[4]
    if pre is None:
        return (major, minor, patch, 1, ())
    parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return (major, minor, patch, 0, parts)


def semver_key(version: str) -> tuple[int, int, int, int, tuple[Any, ...]]:
    """Make a sort key for a semantic version. See `_semver_key`.

    Args:
        version: A semantic version.

    Returns:
        A tuple that can be compared with another one.
    """
    return _semver_key(version)


def satisfies(version: str, specifier: str | None) -> bool:
    """Whether `version` meets a specifier such as ">=1.2.0,<2.0.0" (None: any version).

    "~=1.4.2" means
    ">=1.4.2,<1.5.0"; "~=1.4.0" likewise; a pre-release only meets a clause that names a pre-release.
    """
    if not specifier:
        return True
    key = _semver_key(version)
    for clause in specifier.split(","):
        clause = clause.strip()
        operator = next(op for op in ("~=", ">=", "<=", "==", "!=", ">", "<") if clause.startswith(op))
        bound = clause[len(operator) :].strip()
        other = _semver_key(bound)
        if operator == "~=":
            major, minor = other[0], other[1]
            if not (key >= other and key < (major, minor + 1, 0, 0, ())):
                return False
            continue
        ok = {
            ">=": key >= other,
            "<=": key <= other,
            "==": key == other,
            "!=": key != other,
            ">": key > other,
            "<": key < other,
        }[operator]
        if not ok:
            return False
    return True


def json_schema() -> dict[str, Any]:
    """Make the JSON Schema of the manifest, as served by the hub.

    Returns:
        The schema. Permissions carry a description each, and a requirement may be a bare plugin id.
    """
    schema = Manifest.model_json_schema(by_alias=True)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = SCHEMA_URL
    schema["title"] = "Sudoo plugin manifest v1"
    properties = schema["properties"]
    # editors show each permission's meaning; a requirement may be written as a bare plugin id
    properties["permissions"]["items"] = {
        "type": "string",
        "oneOf": [{"const": key, "description": text} for key, text in PERMISSION_DESCRIPTIONS.items()],
    }
    properties["requires"]["items"] = {
        "anyOf": [{"$ref": "#/$defs/Requirement"}, {"type": "string", "pattern": PLUGIN_ID, "maxLength": 128}]
    }
    return schema


# The name of the manifest file.
MANIFEST_NAME = "manifest.json"
# The largest manifest accepted, in bytes (64 KB).
MAX_MANIFEST_BYTES = 64 * 1024


class ManifestError(ValueError):
    """manifest.json cannot be read at all (missing, too large, not JSON, not an object)."""


def parse_manifest(data: bytes) -> Manifest:
    """The manifest in `data`.

    Args:
        data: The bytes of a manifest.json file.

    Returns:
        The validated manifest.

    Raises:
        ManifestError: When the data is too large, is not UTF-8 JSON or is not a JSON object.
        pydantic.ValidationError: When it is not a valid manifest.
    """
    if len(data) > MAX_MANIFEST_BYTES:
        raise ManifestError("manifest.json is larger than 64 KB.")
    try:
        raw: Any = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ManifestError("manifest.json is not valid JSON (UTF-8).") from None
    if not isinstance(raw, dict):
        raise ManifestError("manifest.json must be a JSON object.")
    return Manifest.model_validate(raw)


def load_manifest(path: Path) -> Manifest:
    """The manifest at `path` (a manifest.json file, or a plugin folder that holds one).

    Args:
        path: The file or the folder.

    Returns:
        The validated manifest.

    Raises:
        ManifestError: When the file does not exist or cannot be read as a manifest.
        pydantic.ValidationError: When it is not a valid manifest.
    """
    if path.is_dir():
        path = path / MANIFEST_NAME
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise ManifestError(f"{path} does not exist.") from None
    return parse_manifest(data)
