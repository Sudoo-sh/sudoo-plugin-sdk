"""The `sudoo-plugin` command.

    sudoo-plugin new <type> <id>        a new plugin project from the built-in templates
    sudoo-plugin validate [path]        the hub's automated checks, locally
    sudoo-plugin test [path]            the plugin's tests against a fake panel
    sudoo-plugin pack [path]            dist/<id>-<version>.sudoo, byte for byte reproducible; prints its SHA-256
    sudoo-plugin verify <package>       check the hub's Ed25519 signature of a package
    sudoo-plugin publish [path|package] upload to the hub's developer endpoint (SUDOO_DEVELOPER_TOKEN)
    sudoo-plugin schema                 the manifest's JSON Schema
    sudoo-plugin types                  plugin types, entry-point groups and the permissions they need

Exit status: 0 success, 1 a check or command failed, 2 wrong usage.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

from sudoo_plugin_sdk import __version__
from sudoo_plugin_sdk.groups import GROUPS
from sudoo_plugin_sdk.manifest import PERMISSION_DESCRIPTIONS, PLUGIN_TYPES, json_schema
from sudoo_plugin_sdk.package import EXTENSION, PackError, pack, read_manifest
from sudoo_plugin_sdk.publish import PublishError, changelog_entry, publish
from sudoo_plugin_sdk.scaffold import ScaffoldError, names_for, scaffold
from sudoo_plugin_sdk.signing import load_public_key, sha256_of, verify_package
from sudoo_plugin_sdk.validate import Report, validate


def _say(text: str = "") -> None:
    """Write a line to standard output.

    Args:
        text: The line, without a line break.
    """
    sys.stdout.write(text + "\n")


def _fail(text: str) -> int:
    """Write a line to standard error.

    Args:
        text: The line, without a line break.

    Returns:
        1, the exit status for a failure.
    """
    sys.stderr.write(text + "\n")
    return 1


def _print_report(report: Report, strict: bool) -> bool:
    """Print the errors, the warnings and a summary line of a report.

    Args:
        report: The validation report.
        strict: When True, warnings also make the result not valid.

    Returns:
        True when the project counts as valid.
    """
    for message in report.errors:
        _say(f"error    {message}")
    for message in report.warnings:
        _say(f"warning  {message}")
    ok = report.ok and not (strict and report.warnings)
    if report.manifest is not None:
        state = "valid" if ok else "not valid"
        _say(f"{report.manifest.id} {report.manifest.version}: {state} "
             f"({len(report.errors)} errors, {len(report.warnings)} warnings)")  # fmt: skip
    return ok


# --------------------------------------------------------------------------- commands


def cmd_new(args: argparse.Namespace) -> int:
    """Run `sudoo-plugin new`.

    Args:
        args: The parsed arguments.

    Returns:
        The exit status.
    """
    try:
        target = Path(args.dir) if args.dir else Path.cwd() / names_for(args.id).entry
        scaffold(args.type, args.id, target, author=args.author)
    except ScaffoldError as error:
        return _fail(str(error))
    _say(f"Created {target}")
    _say(f"  cd {target}\n  uv sync\n  uv run sudoo-plugin validate && uv run sudoo-plugin test")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Run `sudoo-plugin validate`.

    Args:
        args: The parsed arguments.

    Returns:
        The exit status.
    """
    report = validate(Path(args.path), import_code=not args.no_import)
    return 0 if _print_report(report, args.strict) else 1


@contextlib.contextmanager
def _on_path(folder: Path) -> Iterator[None]:
    """Put a folder first on the import path for the duration of a `with` block.

    Args:
        folder: The folder.

    Yields:
        Nothing; the folder is removed from the path again afterwards.
    """
    sys.path.insert(0, str(folder))
    try:
        yield
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(str(folder))


def cmd_test(args: argparse.Namespace) -> int:
    """Run `sudoo-plugin test`: validate the project, then run its tests with pytest.

    Args:
        args: The parsed arguments.

    Returns:
        The exit status.
    """
    project = Path(args.path).resolve()
    report = validate(project, import_code=True)
    if not _print_report(report, strict=False):
        return 1
    try:
        import pytest
    except ImportError:
        return _fail("pytest is not installed: install sudoo-plugin-sdk[test] (uv add --dev 'sudoo-plugin-sdk[test]').")
    tests = project / "tests"
    if not tests.is_dir():
        return _fail(f"{tests} does not exist.")
    with _on_path(project / "src"):
        code = pytest.main(
            [
                "--rootdir",
                str(project),
                "-W",
                "ignore::pytest.PytestAssertRewriteWarning",
                str(tests),
                *args.pytest_args,
            ]
        )
    return 0 if int(code) == 0 else 1


def cmd_pack(args: argparse.Namespace) -> int:
    """Run `sudoo-plugin pack`.

    Args:
        args: The parsed arguments.

    Returns:
        The exit status.
    """
    project = Path(args.path).resolve()
    report = validate(project, import_code=not args.no_import)
    if not _print_report(report, args.strict) or report.manifest is None:
        return _fail("Not packed: fix the errors above.")
    try:
        packed = pack(project, report.manifest, Path(args.out) if args.out else None, compress=args.compress)
    except PackError as error:
        return _fail(f"Not packed:\n{error}")
    _say(f"Packed {packed.path} ({packed.files} files, {packed.size} bytes)")
    _say(f"sha256 {packed.sha256}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Run `sudoo-plugin verify`.

    Args:
        args: The parsed arguments.

    Returns:
        The exit status.
    """
    package = Path(args.package)
    try:
        key_source = Path(args.public_key)
        key_data = key_source.read_bytes() if key_source.is_file() else args.public_key.encode()
        public_key = load_public_key(key_data)
    except (OSError, ValueError) as error:
        return _fail(f"The public key cannot be read: {error}")
    if args.signature:
        signature = args.signature
    else:
        signature_file = Path(args.signature_file) if args.signature_file else Path(str(package) + ".sig")
        try:
            signature = signature_file.read_text(encoding="utf-8").strip()
        except OSError:
            return _fail(f"No signature: give --signature or put it in {signature_file}.")
    try:
        manifest = read_manifest(package)
    except (OSError, ValueError) as error:
        return _fail(str(error))
    sha256 = sha256_of(package)
    if not verify_package(public_key, manifest.id, manifest.version, package, signature, args.sha256):
        return _fail(f"NOT VERIFIED: the signature does not match {manifest.id} {manifest.version} (sha256 {sha256}).")
    _say(f"Verified: {manifest.id} {manifest.version}, sha256 {sha256}")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    """Run `sudoo-plugin publish`.

    Args:
        args: The parsed arguments.

    Returns:
        The exit status.
    """
    target = Path(args.path).resolve()
    if target.is_dir():
        project = target
        report = validate(project, import_code=not args.no_import)
        if not _print_report(report, strict=False) or report.manifest is None:
            return _fail("Not published: fix the errors above.")
        try:
            package = pack(project, report.manifest).path
        except PackError as error:
            return _fail(f"Not published:\n{error}")
        version = report.manifest.version
    else:
        package = target
        # dist/<id>-<version>.sudoo: the project (and its CHANGELOG.md) is usually the folder above dist/
        project = next(
            (p for p in (target.parent, target.parent.parent) if (p / "CHANGELOG.md").is_file()), target.parent
        )
        if package.suffix != EXTENSION:
            return _fail(f"{package} is not a {EXTENSION} package or a plugin folder.")
        try:
            version = read_manifest(package).version
        except (OSError, ValueError) as error:
            return _fail(str(error))
    if args.changelog_file:
        changelog = Path(args.changelog_file).read_text(encoding="utf-8")
    elif args.changelog:
        changelog = args.changelog
    else:
        changelog = changelog_entry(project, version) or ""
        if not changelog:
            return _fail(f"No changelog: add a '## {version}' section to CHANGELOG.md, or give --changelog.")
    try:
        result = publish(package, changelog, hub=args.hub, dry_run=args.dry_run)
    except PublishError as error:
        return _fail(str(error))
    if args.dry_run:
        _say(f"Dry run: would send {package.name} ({result.size} bytes, sha256 {result.sha256})")
        _say(f"  as {result.plugin_id} {result.version} to {result.url}/api/v1/developer/plugins")
        _say("  changelog:\n    " + "\n    ".join(changelog.strip().splitlines()))
        return 0
    data = (result.response or {}).get("data", {})
    _say(f"Submitted {result.plugin_id} {result.version} ({'new plugin' if result.new_plugin else 'new version'})")
    _say(f"  state: {data.get('status', 'submitted')}, sha256 {result.sha256}")
    for check in data.get("checks", []):
        _say(f"  {check.get('status', ''):8} {check.get('name', '')}: {check.get('message', '')}")
    _say("Follow the review on developers.sudoo.sh.")
    return 0 if data.get("status") != "changes_requested" else 1


def cmd_schema(_: argparse.Namespace) -> int:
    """Run `sudoo-plugin schema`.

    Args:
        _: The parsed arguments; not used.

    Returns:
        The exit status.
    """
    _say(json.dumps(json_schema(), indent=2))
    return 0


def cmd_types(_: argparse.Namespace) -> int:
    """Run `sudoo-plugin types`.

    Args:
        _: The parsed arguments; not used.

    Returns:
        The exit status.
    """
    for group in GROUPS:
        state = "available" if group.available else "planned"
        needs = ", ".join(sorted(group.needs)) or "-"
        _say(f"{group.type:17} {group.name:24} {group.interface:20} {state:9} needs: {needs}")
    _say("\nPermissions:")
    for key, text in PERMISSION_DESCRIPTIONS.items():
        _say(f"  {key:17} {text}")
    return 0


def parser() -> argparse.ArgumentParser:
    """Build the argument parser with every command.

    Returns:
        The parser.
    """
    root = argparse.ArgumentParser(prog="sudoo-plugin", description="Build plugins for Sudoo.sh.")
    root.add_argument("--version", action="version", version=f"sudoo-plugin {__version__}")
    commands = root.add_subparsers(dest="command", required=True, metavar="command")

    new = commands.add_parser("new", help="create a plugin project")
    new.add_argument("type", choices=PLUGIN_TYPES, metavar="type", help="plugin type: " + ", ".join(PLUGIN_TYPES))
    new.add_argument("id", help="plugin id, reverse domain: com.example.midnight-theme")
    new.add_argument("--dir", help="folder to create (default: the id's last part)")
    new.add_argument("--author", default="Your name", help="author name for the manifest and licence")
    new.set_defaults(run=cmd_new)

    check = commands.add_parser("validate", help="run the hub's automated checks locally")
    check.add_argument("path", nargs="?", default=".")
    check.add_argument("--no-import", action="store_true", help="do not import the plugin's code")
    check.add_argument("--strict", action="store_true", help="fail on warnings too")
    check.set_defaults(run=cmd_validate)

    test = commands.add_parser("test", help="run the plugin's tests against a fake panel")
    test.add_argument("path", nargs="?", default=".")
    test.add_argument("pytest_args", nargs=argparse.REMAINDER, help="passed to pytest (after --)")
    test.set_defaults(run=cmd_test)

    build = commands.add_parser("pack", help="build the .sudoo package")
    build.add_argument("path", nargs="?", default=".")
    build.add_argument("--out", help="folder for the package (default: dist/)")
    build.add_argument(
        "--compress", action="store_true", help="deflate entries (smaller; same zlib needed to reproduce)"
    )
    build.add_argument("--no-import", action="store_true", help="do not import the plugin's code while checking")
    build.add_argument("--strict", action="store_true", help="fail on warnings too")
    build.set_defaults(run=cmd_pack)

    verify = commands.add_parser("verify", help="check a package's Ed25519 signature")
    verify.add_argument("package")
    verify.add_argument("--public-key", required=True, help="PEM file, or base64url of the 32-byte key")
    verify.add_argument("--signature", help="base64url signature (default: read <package>.sig)")
    verify.add_argument("--signature-file", help="file holding the signature")
    verify.add_argument("--sha256", help="the SHA-256 the catalogue lists; must match too")
    verify.set_defaults(run=cmd_verify)

    send = commands.add_parser("publish", help="upload to the hub (token in SUDOO_DEVELOPER_TOKEN)")
    send.add_argument("path", nargs="?", default=".", help="plugin folder (packed first) or a .sudoo package")
    send.add_argument("--changelog", help="what changed (default: this version's section of CHANGELOG.md)")
    send.add_argument("--changelog-file", help="file with what changed")
    send.add_argument("--hub", help="hub address (default: SUDOO_HUB_URL or https://hub.sudoo.sh)")
    send.add_argument("--dry-run", action="store_true", help="check and show what would be sent; send nothing")
    send.add_argument("--no-import", action="store_true", help="do not import the plugin's code while checking")
    send.set_defaults(run=cmd_publish)

    commands.add_parser("schema", help="print the manifest's JSON Schema").set_defaults(run=cmd_schema)
    commands.add_parser("types", help="list plugin types and permissions").set_defaults(run=cmd_types)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line.

    Args:
        argv: The arguments; None to read them from the process.

    Returns:
        The exit status.
    """
    args = parser().parse_args(argv)
    if getattr(args, "pytest_args", None) and args.pytest_args[0] == "--":
        args.pytest_args = args.pytest_args[1:]
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
