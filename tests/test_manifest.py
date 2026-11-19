"""The manifest model must accept and refuse exactly what the hub does: these cases mirror the hub's own tests,
and the JSON Schema must be the one the hub serves (tests/data/hub-manifest-schema.json, produced by the hub's
hub.schemas.manifest.json_schema(); refresh it when the hub's model changes)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from sudoo_plugin_sdk.manifest import (
    PERMISSION_DESCRIPTIONS,
    PERMISSIONS,
    SCHEMA_URL,
    Manifest,
    ManifestError,
    json_schema,
    load_manifest,
    parse_manifest,
    satisfies,
    semver_key,
)

EXAMPLE: dict[str, Any] = {  # the example of ROADMAP section 11
    "$schema": SCHEMA_URL,
    "id": "com.sudoo.smtp",
    "name": "SMTP Mailer",
    "version": "1.0.0",
    "sdk_version": ">=2.0.0",
    "min_sudoo_version": "2.0.0",
    "max_sudoo_version": None,
    "author": {"name": "Yousef M. Y. Al Sabbah", "org": "Sudoo", "email": "yousef@sudoo.sh", "url": "https://sudoo.sh"},
    "description": "Send emails through any SMTP server (Gmail, Outlook, SendGrid, custom).",
    "long_description_file": "README.md",
    "license": "MIT",
    "type": "mailer",
    "tags": ["email", "smtp", "notifications"],
    "entry_points": {"sudoo.mailers": {"smtp": "sudoo_plugin_smtp.plugin:Smtp"}},
    "settings": [
        {
            "key": "smtp_host",
            "type": "string",
            "label": "SMTP Server",
            "description": "The mail server; empty means no email.",
            "default": "",
            "editable": True,
        },
        {"key": "smtp_port", "type": "integer", "label": "SMTP Port", "default": 587, "editable": True},
    ],
    "permissions": ["network.outbound"],
    "tier": "free",
    "price": None,
    "icon": "icon.svg",
    "screenshots": ["screenshots/settings.png", "screenshots/email-preview.png"],
    "homepage": "https://github.com/Yosef-AlSabbah/sudoo-plugin-smtp",
    "issues": "https://github.com/Yosef-AlSabbah/sudoo-plugin-smtp/issues",
    "signature": None,
}


def _with(**changes: Any) -> dict[str, Any]:
    manifest = copy.deepcopy(EXAMPLE)
    manifest.update(changes)
    return manifest


def test_the_roadmap_example_is_valid() -> None:
    manifest = Manifest.model_validate(EXAMPLE)
    assert manifest.id == "com.sudoo.smtp"
    assert manifest.model_dump(by_alias=True, mode="json")["$schema"] == SCHEMA_URL


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "SMTP"},
        {"id": "com.sudoo"},  # needs at least three parts
        {"id": "com..smtp"},
        {"version": "1.0"},
        {"version": "v1.0.0"},
        {"min_sudoo_version": "01.0.0"},
        {"sdk_version": "2.0.0; rm -rf /"},
        {"type": "rootkit"},
        {"tier": "paid"},  # no price
        {"price": 500},  # free with a price
        {"icon": "../../etc/passwd"},
        {"icon": "/abs/icon.svg"},
        {"screenshots": ["screenshots\\evil.png"]},
        {"homepage": "http://insecure.example"},
        {"homepage": "javascript:alert(1)"},
        {"permissions": ["root"]},
        {"permissions": ["network.outbound", "network.outbound"]},
        {"tags": ["Has Spaces"]},
        {"entry_points": {}},
        {"entry_points": {"other.group": {"x": "a.b:C"}}},
        {"entry_points": {"sudoo.mailers": {"smtp": "os.system"}}},
        {"license": "MIT; DROP TABLE"},
        {"signature": "abc"},
        {"max_sudoo_version": "1.0.0"},  # lower than min
        {"unexpected": True},
        {"$schema": "https://evil.example/schema.json"},
        {"requires": ["com.sudoo.smtp"]},  # itself
        {"requires": ["com.sudoo.api", {"id": "com.sudoo.api"}]},  # twice
        {"requires": [{"id": "com.sudoo.api", "version": "latest"}]},
    ],
)
def test_invalid_manifests_are_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Manifest.model_validate(_with(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"entry_points": {"sudoo.mailers\n": {"smtp": "sudoo_plugin_smtp.plugin:Smtp"}}},
        {"entry_points": {"sudoo.mailers": {"smtp\n": "sudoo_plugin_smtp.plugin:Smtp"}}},
        {"entry_points": {"sudoo.mailers": {"smtp": "sudoo_plugin_smtp.plugin:Smtp\n"}}},
        {"id": "com.sudoo.smtp\n"},
        {"version": "1.0.0\n"},
        {"tags": ["email\n"]},
        {"license": "MIT\n"},
        {"settings": [{"key": "host\n", "type": "string", "label": "Host"}]},
    ],
)
def test_a_trailing_newline_is_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Manifest.model_validate(_with(**changes))


@pytest.mark.parametrize(
    "setting",
    [
        {"key": "port", "type": "integer", "label": "Port", "default": "587"},
        {"key": "flag", "type": "integer", "label": "Flag", "default": True},
        {"key": "token", "type": "secret", "label": "Token", "default": "hunter2"},
        {"key": "mode", "type": "choice", "label": "Mode"},
        {"key": "mode", "type": "choice", "label": "Mode", "choices": ["a"], "default": "b"},
        {"key": "Bad-Key", "type": "string", "label": "X"},
    ],
)
def test_invalid_settings_are_refused(setting: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Manifest.model_validate(_with(settings=[setting]))


def test_duplicate_setting_keys_are_refused() -> None:
    setting = {"key": "host", "type": "string", "label": "Host"}
    with pytest.raises(ValidationError):
        Manifest.model_validate(_with(settings=[setting, setting]))


def test_paid_plugin_with_price() -> None:
    assert Manifest.model_validate(_with(tier="paid", price=2900)).price == 2900


def test_requirements_as_bare_ids_or_objects() -> None:
    manifest = Manifest.model_validate(_with(requires=["com.sudoo.api", {"id": "com.sudoo.mcp", "version": ">=1.0.0"}]))
    assert [(r.id, r.version) for r in manifest.requires] == [("com.sudoo.api", None), ("com.sudoo.mcp", ">=1.0.0")]


def test_fourteen_permissions_each_described() -> None:
    assert len(PERMISSIONS) == 14
    assert set(PERMISSIONS) == set(PERMISSION_DESCRIPTIONS)


def test_semver_order() -> None:
    versions = ["1.0.0", "1.10.0", "1.9.0", "1.10.0-rc.1", "1.10.0-alpha", "2.0.0-beta.2", "2.0.0-beta.11"]
    assert sorted(versions, key=semver_key) == [
        "1.0.0",
        "1.9.0",
        "1.10.0-alpha",
        "1.10.0-rc.1",
        "1.10.0",
        "2.0.0-beta.2",
        "2.0.0-beta.11",
    ]


@pytest.mark.parametrize(
    ("version", "specifier", "expected"),
    [
        ("1.2.0", None, True),
        ("1.2.0", ">=1.0.0,<2.0.0", True),
        ("2.0.0", ">=1.0.0,<2.0.0", False),
        ("1.4.9", "~=1.4.2", True),
        ("1.5.0", "~=1.4.2", False),
        ("1.0.0", "!=1.0.0", False),
    ],
)
def test_satisfies(version: str, specifier: str | None, expected: bool) -> None:
    assert satisfies(version, specifier) is expected


def test_the_json_schema_is_the_hubs() -> None:
    hub = json.loads((Path(__file__).parent / "data" / "hub-manifest-schema.json").read_text())
    assert json.loads(json.dumps(json_schema())) == hub
    assert hub["$id"] == SCHEMA_URL


def test_parse_and_load(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps(EXAMPLE))
    assert load_manifest(tmp_path).id == "com.sudoo.smtp"
    with pytest.raises(ManifestError):
        parse_manifest(b"[1, 2]")
    with pytest.raises(ManifestError):
        parse_manifest(b"{not json")
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "missing")
