"""`sudoo-plugin new <type> <id>`: a plugin project that validates, tests and packs as it is.

    <folder>/
      manifest.json  pyproject.toml  README.md  CHANGELOG.md  LICENSE.md  .gitignore
      src/<module>/__init__.py  src/<module>/plugin.py   (+ tokens.css, logo.svg for a theme)
      tests/test_plugin.py

The class in plugin.py is written from the interface of the group: every method is there, raising
NotImplementedError until you fill it in. A theme is complete at once (a starter palette and logo).
"""

from __future__ import annotations

import builtins
import collections.abc
import inspect
import json
import pathlib
import re
import typing
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from sudoo_plugin_sdk import __version__, context, plugins
from sudoo_plugin_sdk.groups import BY_TYPE
from sudoo_plugin_sdk.manifest import PLUGIN_ID, PLUGIN_TYPES, SCHEMA_URL, Manifest
from sudoo_plugin_sdk.plugins import core, planned
from sudoo_plugin_sdk.validate import protocol_methods

SDK_GIT_URL = "https://github.com/Sudoo-sh/sudoo-plugin-sdk"


class ScaffoldError(ValueError):
    """The project cannot be created; the message says why."""

    pass


@dataclass(frozen=True)
class Names:
    """The names derived from a plugin id.

    Attributes:
        plugin_id: The plugin's id.
        entry: The entry point name: the id's last part, for example "midnight-theme" (at most 41 characters).
        module: The Python package name, for example "example_midnight_theme".
        distribution: The distribution name, for example "sudoo-plugin-midnight-theme".
        title: A readable title, for example "Midnight theme".
        class_name: The plugin class name, for example "MidnightTheme".
    """

    plugin_id: str
    entry: str  # entry-point name: the id's last part, "midnight-theme"
    module: str  # Python package: "example_midnight_theme"
    distribution: str  # "sudoo-plugin-midnight-theme"
    title: str  # "Midnight theme"
    class_name: str  # "MidnightTheme"


def names_for(plugin_id: str) -> Names:
    """Derive the names of a plugin project from its id.

    Args:
        plugin_id: The plugin's id.

    Returns:
        The names.

    Raises:
        ScaffoldError: When the id does not match the plugin id pattern.
    """
    if not re.fullmatch(PLUGIN_ID, plugin_id):
        raise ScaffoldError(
            f"{plugin_id!r} is not a plugin id: reverse domain, lower case, at least three parts (com.example.backup)."
        )
    parts = plugin_id.split(".")
    last = parts[-1]
    words = re.split(r"[-_]", last)
    return Names(
        plugin_id=plugin_id,
        entry=last[:41],
        module="_".join(parts[1:]).replace("-", "_"),
        distribution=f"sudoo-plugin-{last}",
        title=" ".join(words).capitalize(),
        class_name="".join(word.capitalize() for word in words),
    )


def sdk_requirement() -> str:
    """The SDK version specifier written into new projects.

    Returns:
        A specifier from the running version up to, not including, the next major version.
    """
    major = int(__version__.split(".")[0])
    return f">={__version__},<{major + 1}.0.0"


# --------------------------------------------------------------------------- the class, from the interface

# Where a name used in an interface is imported from, first match wins: the standard library, then the SDK's
# public modules, then the modules that define the remaining aliases (Log, Account, Handler ...).
_KNOWN_MODULES: tuple[tuple[str, object], ...] = (
    ("collections.abc", collections.abc),
    ("pathlib", pathlib),
    ("typing", typing),
    ("sudoo_plugin_sdk.plugins", plugins),
    ("sudoo_plugin_sdk.context", context),
    ("sudoo_plugin_sdk.plugins.core", core),
    ("sudoo_plugin_sdk.plugins.planned", planned),
)
MAX_LINE = 120
_PLACEHOLDERS = {"str": '""', "bool": "False", "int": "60", "str | None": "None"}


def _imports_for(annotations: list[str]) -> list[str]:
    """Make the import lines for the names used in some annotations.

    Args:
        annotations: Annotation texts.

    Returns:
        Sorted import lines. A name is taken from the first of the known modules that has it; built-in names need no import.
    """
    wanted: dict[str, set[str]] = {}
    for text in annotations:
        for name in sorted(set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))):
            if hasattr(builtins, name) or name == "None":
                continue
            for module_name, module in _KNOWN_MODULES:
                if hasattr(module, name):
                    wanted.setdefault(module_name, set()).add(name)
                    break
    return [f"from {module} import {', '.join(sorted(items))}" for module, items in sorted(wanted.items())]


def _render_method(protocol: type, name: str) -> tuple[str, list[str]]:
    """Write one interface method as a stub that raises NotImplementedError.

    Args:
        protocol: The Protocol class.
        name: The method's name.

    Returns:
        The method's source, and the annotation texts it uses.
    """
    function = protocol.__dict__[name]
    signature = inspect.signature(function)
    params: list[str] = []
    annotations: list[str] = []
    for parameter in signature.parameters.values():
        text = parameter.name
        if parameter.annotation is not inspect.Parameter.empty:
            annotation = str(parameter.annotation)
            annotations.append(annotation)
            text += f": {annotation}"
        if parameter.default is not inspect.Parameter.empty:
            text += f" = {parameter.default!r}" if ":" in text else f"={parameter.default!r}"
        params.append(text)
    returns = "" if signature.return_annotation is inspect.Signature.empty else str(signature.return_annotation)
    if returns:
        annotations.append(returns)
    doc = inspect.getdoc(function)
    ending = f" -> {returns}:" if returns else ":"
    lines = [f"    def {name}({', '.join(params)}){ending}"]
    if len(lines[0]) > MAX_LINE:
        lines = [f"    def {name}(", *(f"        {param}," for param in params), f"    ){ending}"]
    if doc:
        lines.append(f'        """{doc.splitlines()[0]}"""')
    lines.append(f'        raise NotImplementedError("{name}")')
    return "\n".join(lines), annotations


def render_plugin_class(plugin_type: str, names: Names) -> str:
    """Write plugin.py for a plugin type, from the interface of its entry-point group.

    Args:
        plugin_type: The plugin type.
        names: The names of the project.

    Returns:
        The source of the module.
    """
    group = BY_TYPE[plugin_type]
    protocol: Any = getattr(plugins, group.interface)
    attributes: list[str] = []
    annotations: list[str] = []
    for name, annotation in getattr(protocol, "__annotations__", {}).items():
        text = str(annotation)
        annotations.append(text)
        value = _PLACEHOLDERS.get(text, "frozenset()" if text.startswith("frozenset") else "None")
        if name in ("name",):
            value = json.dumps(names.entry)
        elif name in ("label",):
            value = json.dumps(names.title)
        attributes.append(f"    {name}: {text} = {value}")
    members: list[str] = []
    for name in sorted(getattr(protocol, "__protocol_attrs__", set())):
        member = protocol.__dict__.get(name)
        if isinstance(member, property) and member.fget is not None:
            returns = str(inspect.signature(member.fget).return_annotation)
            annotations.append(returns)
            members.append(f"    @property\n    def {name}(self) -> {returns}:\n        return False")
    for name in protocol_methods(protocol):
        rendered, used = _render_method(protocol, name)
        members.append(rendered)
        annotations.extend(used)
    imports = _imports_for(annotations)
    standard = sorted(line for line in imports if not line.startswith("from sudoo_plugin_sdk"))
    sdk = sorted({*(line for line in imports if line.startswith("from sudoo_plugin_sdk")),
                  "from sudoo_plugin_sdk import SudooPlugin"})  # fmt: skip
    head = [
        f'"""{names.title}: a plugin for Sudoo.sh ({group.name})."""',
        "",
        "from __future__ import annotations",
        "",
        *standard,
        *([""] if standard else []),
        *sdk,
        "",
        "",
        f"class {names.class_name}(SudooPlugin):",
        f'    """{group.description}. Implements {group.interface}."""',
        "",
    ]
    body = attributes + ([""] if attributes else []) + ["\n\n".join(members) if members else "    pass"]
    return "\n".join(head + body) + "\n"


THEME_CLASS = '''"""{title}: a theme for the Sudoo.sh panel (sudoo.themes)."""

from __future__ import annotations

from sudoo_plugin_sdk import Theme


class {class_name}(Theme):
    """Colours in tokens.css (light and dark), the logo, and the accent of the panel's e-mails."""

    label = "{label}"
    tokens = "tokens.css"
    logo = "logo.svg"
    email_accent = "#2f5d8a"
'''


# --------------------------------------------------------------------------- the files


def manifest_for(plugin_type: str, names: Names, author: str) -> dict[str, Any]:
    """Make the manifest of a new project.

    Args:
        plugin_type: The plugin type.
        names: The names of the project.
        author: The author's name.

    Returns:
        The manifest as a dictionary, checked against the `Manifest` model.
    """
    group = BY_TYPE[plugin_type]
    data: dict[str, Any] = {
        "$schema": SCHEMA_URL,
        "id": names.plugin_id,
        "name": names.title if len(names.title) >= 2 else names.plugin_id,
        "version": "0.1.0",
        "sdk_version": sdk_requirement(),
        "min_sudoo_version": "2.0.0",
        "author": {"name": author},
        "description": f"{group.description}.",
        "long_description_file": "README.md",
        "license": "MIT",
        "type": plugin_type,
        "tags": [plugin_type.replace("_", "-")],
        "entry_points": {group.name: {names.entry: f"{names.module}.plugin:{names.class_name}"}},
        "settings": [],
        "permissions": sorted(group.needs),
        "tier": "free",
    }
    Manifest.model_validate(data)  # what we write must be valid
    return data


def pyproject_for(names: Names, manifest: dict[str, Any]) -> str:
    """Make the pyproject.toml of a new project.

    Args:
        names: The names of the project.
        manifest: The manifest data made for it.

    Returns:
        The file's text.
    """
    entry_points = "\n".join(
        f'[project.entry-points."{group}"]\n' + "\n".join(f'{name} = "{target}"' for name, target in entries.items())
        for group, entries in manifest["entry_points"].items()
    )
    return f"""[project]
name = "{names.distribution}"
version = "{manifest["version"]}"
description = "{manifest["description"]}"
readme = "README.md"
license = "MIT"
license-files = ["LICENSE.md"]
requires-python = ">=3.12"
dependencies = ["sudoo-plugin-sdk{manifest["sdk_version"]}"]

{entry_points}

[build-system]
requires = ["uv_build>=0.13.8,<0.14.0"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "{names.module}"

# Until sudoo-plugin-sdk is on PyPI it comes from its Git repository (see README).
[tool.uv.sources]
sudoo-plugin-sdk = {{ git = "{SDK_GIT_URL}" }}

[dependency-groups]
dev = ["sudoo-plugin-sdk[test]{manifest["sdk_version"]}", "pytest>=9.2.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.black]
line-length = 120

[tool.ruff]
line-length = 120
src = ["src", "tests"]

[tool.ruff.lint.isort]
known-first-party = ["{names.module}"]
"""


def test_for(plugin_type: str, names: Names) -> str:
    """Make the starter test file of a new project.

    Args:
        plugin_type: The plugin type.
        names: The names of the project.

    Returns:
        The file's text. A theme gets checks of the theme; other types get an interface check.
    """
    group = BY_TYPE[plugin_type]
    if plugin_type == "theme":
        return f"""from {names.module}.plugin import {names.class_name}


def test_the_theme_passes_every_check() -> None:
    report = {names.class_name}.check()
    assert report.errors == []


def test_dark_mode_has_its_own_accent() -> None:
    report = {names.class_name}.check()
    assert report.dark["--accent"] != report.light["--accent"]
"""
    return f"""from sudoo_plugin_sdk.context import PluginContext
from sudoo_plugin_sdk.plugins import {group.interface}

from {names.module}.plugin import {names.class_name}


def test_it_implements_the_interface(sudoo_context: PluginContext) -> None:
    plugin = {names.class_name}(sudoo_context)
    assert isinstance(plugin, {group.interface})
"""


README = """# {title}

{description}

A plugin for [Sudoo.sh](https://sudoo.sh) ({group}), built with the Sudoo.sh plugin SDK.

## Develop

```bash
uv sync                      # the SDK and pytest
uv run sudoo-plugin validate # what the hub checks
uv run sudoo-plugin test     # the tests, against a fake panel
uv run sudoo-plugin pack     # dist/{plugin_id}-0.1.0.sudoo
```

## Licence

MIT, see LICENSE.md.
"""

CHANGELOG = """# Changelog

## 0.1.0

- First version.
"""

LICENSE = """# MIT License

Copyright (c) {year} {author}

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

GITIGNORE = """__pycache__/
*.py[oc]
.venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
*.egg-info/
.env
.env.*
*.pem
*.key
"""


def scaffold(plugin_type: str, plugin_id: str, target: Path, *, author: str = "Your name", year: int = 2026) -> Path:
    """Write a new plugin project into `target`.

    Args:
        plugin_type: The plugin type.
        plugin_id: The plugin's id.
        target: The folder to create. It must not exist or must be empty.
        author: The author's name for the manifest and the licence.
        year: The year for the licence.

    Returns:
        The target folder.

    Raises:
        ScaffoldError: When the type is unknown, the folder is not empty or the id is not valid.
    """
    if plugin_type not in PLUGIN_TYPES:
        raise ScaffoldError(f"{plugin_type!r} is not a plugin type. Types: {', '.join(PLUGIN_TYPES)}.")
    if target.exists() and any(target.iterdir()):
        raise ScaffoldError(f"{target} exists and is not empty.")
    names = names_for(plugin_id)
    manifest = manifest_for(plugin_type, names, author)
    package = target / "src" / names.module
    files: dict[Path, str] = {
        target / "manifest.json": json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        target / "pyproject.toml": pyproject_for(names, manifest),
        target
        / "README.md": README.format(
            title=names.title,
            description=manifest["description"],
            group=BY_TYPE[plugin_type].name,
            plugin_id=plugin_id,
        ),
        target / "CHANGELOG.md": CHANGELOG,
        target / "LICENSE.md": LICENSE.format(year=year, author=author),
        target / ".gitignore": GITIGNORE,
        package / "__init__.py": f'"""{names.title}."""\n',
        target / "tests" / "test_plugin.py": test_for(plugin_type, names),
    }
    if plugin_type == "theme":
        files[package / "plugin.py"] = THEME_CLASS.format(
            title=names.title, class_name=names.class_name, label=names.title[:40]
        )
        assets = resources.files("sudoo_plugin_sdk.templates").joinpath("theme")
        files[package / "tokens.css"] = assets.joinpath("tokens.css").read_text(encoding="utf-8")
        files[package / "logo.svg"] = assets.joinpath("logo.svg").read_text(encoding="utf-8")
    else:
        files[package / "plugin.py"] = render_plugin_class(plugin_type, names)
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return target
