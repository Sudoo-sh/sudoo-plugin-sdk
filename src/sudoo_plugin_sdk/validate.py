"""`sudoo-plugin validate`: everything the hub's automated checks look at, before you upload.

manifest       the hub's rules (sudoo_plugin_sdk.manifest)
structure      what goes into the package, forbidden files, sizes, README / LICENSE / CHANGELOG / tests
groups         the manifest `type` has its entry-point group; every group is one the panel knows
permissions    each group's required permissions are asked for; nothing is asked for that no group uses;
               themes ask for none
pyproject      [project.entry-points] and the version agree with manifest.json
code           (unless --no-import) every entry point imports and has its interface's methods; themes pass
               the theme checks (tokens, logo, e-mail accent)
scan           the hub's static scan: dynamic code execution and shell calls are flagged for the reviewer
"""

from __future__ import annotations

import contextlib
import importlib
import inspect
import re
import sys
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from sudoo_plugin_sdk import __version__, plugins
from sudoo_plugin_sdk.groups import BY_NAME, BY_TYPE
from sudoo_plugin_sdk.manifest import Manifest, ManifestError, load_manifest, satisfies
from sudoo_plugin_sdk.package import collect
from sudoo_plugin_sdk.plugins.base import SudooPlugin
from sudoo_plugin_sdk.theme import Theme, check_logo_svg

# Entry-point groups whose plugins serve requests, so that the network.inbound permission makes sense.
SERVES_REQUESTS = frozenset(
    {"sudoo.update_triggers", "sudoo.api_access", "sudoo.api_blueprints", "sudoo.mcp", "sudoo.web_pages"}
)
# The hub's built-in scanner: patterns of dynamic code execution and shell calls, each with a label.
SCAN_PATTERNS = (  # the hub's built-in scanner (python_patterns)
    (re.compile(r"\beval\s*\("), "eval()"),
    (re.compile(r"\bexec\s*\("), "exec()"),
    (re.compile(r"\bos\.system\s*\("), "os.system()"),
    (re.compile(r"\bsubprocess\.[A-Za-z_]+\s*\("), "subprocess"),
    (re.compile(r"\bpickle\.loads?\s*\("), "pickle.load()"),
    (re.compile(r"\b__import__\s*\("), "__import__()"),
    (re.compile(r"\bcompile\s*\([^)]*['\"]exec['\"]"), "compile(..., 'exec')"),
)


@dataclass
class Report:
    """The result of validating a project.

    Attributes:
        errors: Problems that stop the upload.
        warnings: Things the hub flags for the reviewer or that are worth a look.
        manifest: The manifest, when it could be read; otherwise None.
    """

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest: Manifest | None = None

    @property
    def ok(self) -> bool:
        """Tell whether there are no errors.

        Returns:
            True when `errors` is empty.
        """
        return not self.errors


def manifest_errors(error: ValidationError) -> list[str]:
    """The hub's way of naming the fields of an invalid manifest.

    Args:
        error: The pydantic error.

    Returns:
        One line per problem, like "manifest.version: <message>".
    """
    return [
        "manifest." + ".".join(str(part) for part in item["loc"]) + f": {item['msg']}"
        for item in error.errors(include_input=False, include_url=False)
    ]


def validate(project: Path, *, import_code: bool = True) -> Report:
    """Run every check on a plugin project.

    Args:
        project: The plugin's folder.
        import_code: When False, the entry points are not imported.

    Returns:
        The report.
    """
    report = Report()
    project = project.resolve()
    try:
        manifest = load_manifest(project)
    except ManifestError as error:
        report.errors.append(str(error))
        return report
    except ValidationError as error:
        report.errors.extend(manifest_errors(error))
        return report
    report.manifest = manifest

    _structure(project, manifest, report)
    _groups_and_permissions(manifest, report)
    _pyproject(project, manifest, report)
    if import_code:
        _code(project, manifest, report)
    _scan(project, report)
    if not satisfies(__version__, manifest.sdk_version):
        report.warnings.append(
            f"sdk_version {manifest.sdk_version!r} does not include this SDK ({__version__}); check the interfaces "
            "you use against the CHANGELOG."
        )
    return report


def _structure(project: Path, manifest: Manifest, report: Report) -> None:
    """Check what goes into the package and the files a plugin should have.

    Args:
        project: The plugin's folder.
        manifest: The plugin's manifest.
        report: The report to add to.
    """
    contents = collect(project, manifest)
    report.errors.extend(contents.errors)
    report.warnings.extend(contents.warnings)
    names = set(contents.files)
    if not any(name.upper().startswith("README") for name in names):
        report.warnings.append("No README: the marketplace shows it as the plugin's page.")
    if not any(name.upper().startswith("LICENSE") for name in names):
        report.warnings.append(f"No LICENSE file next to the manifest's licence ({manifest.license}).")
    if not any(name.upper().startswith("CHANGELOG") for name in names):
        report.warnings.append("No CHANGELOG: the hub asks what changed in each version.")
    if not (project / "tests").is_dir():
        report.warnings.append("No tests/ folder: reviewers look for tests.")
    if "pyproject.toml" not in names:
        report.warnings.append("No pyproject.toml: the panel installs the plugin's dependencies from it.")
    if manifest.icon and manifest.icon.endswith(".svg") and (project / manifest.icon).is_file():
        report.errors.extend(f"{manifest.icon}: {p}" for p in check_logo_svg((project / manifest.icon).read_bytes()))


def _groups_and_permissions(manifest: Manifest, report: Report) -> None:
    """Check the entry-point groups and the permissions against each other.

    Args:
        manifest: The plugin's manifest.
        report: The report to add to.
    """
    groups = set(manifest.entry_points)
    for name in sorted(groups):
        if name not in BY_NAME:
            known = ", ".join(sorted(BY_NAME))
            report.errors.append(f"The panel has no entry-point group {name}. Known groups: {known}.")
    main = BY_TYPE[manifest.type]
    if manifest.type != "extension" and main.name not in groups:
        report.errors.append(
            f"A plugin of type {manifest.type} registers under {main.name}; entry_points has no such group."
        )
    permissions = set(manifest.permissions)
    if manifest.type == "theme":
        if permissions:
            report.errors.append(
                "A theme is colours, a logo and an e-mail accent: it needs no permission. Remove: "
                + ", ".join(sorted(permissions))
                + "."
            )
        if groups - {main.name}:
            report.warnings.append("A theme that also registers other groups is reviewed as a full plugin.")
        return
    for name in sorted(groups):
        group = BY_NAME.get(name)
        if group is None:
            continue
        missing = sorted(group.needs - permissions)
        if missing:
            report.errors.append(f"{name} cannot work without the permission(s) {', '.join(missing)}.")
        hinted = sorted(group.usually - group.needs - permissions)
        if hinted:
            report.warnings.append(f"Plugins under {name} usually ask for {', '.join(hinted)}; add it if you use it.")
        if not group.available:
            report.warnings.append(f"{name} is planned for Sudoo.sh 2.0: its interface may still change.")
    if "network.inbound" in permissions and not groups & SERVES_REQUESTS:
        report.warnings.append(
            "network.inbound is asked for, but no entry point serves requests (update triggers, API access, API "
            "routes, MCP, web pages)."
        )
    if "storage.write" in permissions and "storage.read" not in permissions:
        report.warnings.append("storage.write without storage.read: the plugin could not read back what it wrote.")
    if "docker" in permissions:
        report.warnings.append("docker is close to full control of the server; reviewers look hard at why.")


def _pyproject(project: Path, manifest: Manifest, report: Report) -> None:
    """Check that the entry points and the version in pyproject.toml agree with the manifest.

    Args:
        project: The plugin's folder.
        manifest: The plugin's manifest.
        report: The report to add to.
    """
    path = project / "pyproject.toml"
    if not path.is_file():
        return
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        report.errors.append(f"pyproject.toml cannot be read: {error}")
        return
    project_table: dict[str, Any] = data.get("project", {})
    declared: dict[str, dict[str, str]] = {
        group: dict(entries)
        for group, entries in project_table.get("entry-points", {}).items()
        if group.startswith("sudoo.")
    }
    if declared != manifest.entry_points:
        report.errors.append(
            "The sudoo.* groups of [project.entry-points] in pyproject.toml differ from entry_points in "
            "manifest.json; they must be the same."
        )
    version = project_table.get("version")
    if version is not None and version != manifest.version:
        report.errors.append(f"pyproject.toml says version {version}, manifest.json says {manifest.version}.")


@contextlib.contextmanager
def _importable(folder: Path) -> Iterator[None]:
    """Import from `folder` for a moment, then forget every module imported from it.

    Args:
        folder: The folder to add to the import path.

    Yields:
        Nothing; the body of the `with` block runs while the folder is importable.
    """
    before = set(sys.modules)
    sys.path.insert(0, str(folder))
    importlib.invalidate_caches()
    try:
        yield
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(str(folder))
        for name in set(sys.modules) - before:
            module = sys.modules.get(name)
            source = getattr(module, "__file__", None) or ""
            if source and Path(source).resolve().is_relative_to(folder):
                del sys.modules[name]


def load_target(target: str) -> Any:
    """Import the object an entry point names.

    Args:
        target: Text like "module.path:Object" (the object may have dots).

    Returns:
        The object.
    """
    module_name, _, attribute = target.partition(":")
    value: Any = importlib.import_module(module_name)
    for part in attribute.split("."):
        value = getattr(value, part)
    return value


def protocol_methods(protocol: type) -> list[str]:
    """List the methods a Protocol class requires.

    Args:
        protocol: The Protocol class.

    Returns:
        The sorted method names.
    """
    attrs: set[str] = set(getattr(protocol, "__protocol_attrs__", set()))
    return sorted(name for name in attrs if inspect.isfunction(protocol.__dict__.get(name)))


def _code(project: Path, manifest: Manifest, report: Report) -> None:
    """Import each entry point and check its class against the group's interface.

    Args:
        project: The plugin's folder.
        manifest: The plugin's manifest.
        report: The report to add to.

    Side effects:
        Imports the plugin's modules from its src/ folder.
    """
    src = project / "src"
    if not src.is_dir():
        return
    with _importable(src.resolve()):
        for group_name, entries in sorted(manifest.entry_points.items()):
            group = BY_NAME.get(group_name)
            for entry_name, target in sorted(entries.items()):
                where = f"{group_name}: {entry_name} = {target}"
                try:
                    value = load_target(target)
                except Exception as error:  # any import-time failure is the developer's to see
                    report.errors.append(f"{where} cannot be imported: {type(error).__name__}: {error}")
                    continue
                if not inspect.isclass(value):
                    report.errors.append(f"{where} is not a class.")
                    continue
                source = inspect.getsourcefile(value)
                if source is None or not Path(source).resolve().is_relative_to(src.resolve()):
                    report.errors.append(f"{where} is defined outside src/, so it would not be in the package.")
                if group is None:
                    continue
                if issubclass(value, SudooPlugin):
                    missing = sorted(value.required_permissions - set(manifest.permissions))
                    if missing:
                        report.errors.append(f"{where} needs the permission(s) {', '.join(missing)}.")
                if group.name == "sudoo.themes":
                    _theme(value, where, report)
                    continue
                interface = getattr(plugins, group.interface, None)
                if isinstance(interface, type):
                    absent = [name for name in protocol_methods(interface) if not hasattr(value, name)]
                    if absent:
                        report.errors.append(f"{where} lacks {', '.join(absent)} of {group.interface}.")


def _theme(value: type, where: str, report: Report) -> None:
    """Check a theme class.

    Args:
        value: The class an entry point names.
        where: Text that says which entry point it is, for messages.
        report: The report to add to.
    """
    if not issubclass(value, Theme):
        report.errors.append(f"{where} must subclass sudoo_plugin_sdk.Theme.")
        return
    result = value.check()
    report.errors.extend(f"{where}: {message}" for message in result.errors)
    report.warnings.extend(f"{where}: {message}" for message in result.warnings)


def _scan(project: Path, report: Report) -> None:
    """Scan the plugin's Python files for the patterns in `SCAN_PATTERNS`.

    Args:
        project: The plugin's folder.
        report: The report to add to.
    """
    src = project / "src"
    if not src.is_dir():
        return
    found: list[str] = []
    for path in sorted(src.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern, label in SCAN_PATTERNS:
            if pattern.search(text):
                found.append(f"{label} in {path.relative_to(project).as_posix()}")
    if found:
        report.warnings.append("The hub flags for the reviewer: " + "; ".join(found) + ".")
