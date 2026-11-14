"""The .sudoo package: what goes in it, and how it is written so the same sources always give the same bytes.

A package is a ZIP archive with manifest.json at its root:

    manifest.json        required
    pyproject.toml       the Python project (dependencies, entry points)
    README*, CHANGELOG*, LICENSE*
    the manifest's long_description_file, icon and screenshots
    src/**               the plugin's code and the files it ships (theme tokens, templates, web bundles)
    assets/**            other files the plugin reads at run time

Tests, caches and hidden files are left out. Files the hub refuses (keys, .env, repository data) stop the build.

Deterministic: entries sorted by path, every timestamp 1980-01-01 00:00:00, permissions 0644, no directory entries,
no extra fields and no archive comment. Entries are stored (not compressed) by default, so the bytes do not depend
on the zlib build either; `compress=True` uses deflate at level 9, deterministic for one zlib build.
"""

from __future__ import annotations

import fnmatch
import io
import stat
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sudoo_plugin_sdk.manifest import MANIFEST_NAME, Manifest, parse_manifest
from sudoo_plugin_sdk.signing import sha256_of

EXTENSION = ".sudoo"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o100644
# The hub's limits (hub.sudoo.sh defaults): larger packages are refused there.
MAX_PACKAGE_BYTES = 25 * 1024 * 1024
MAX_PACKAGE_FILES = 5000
MAX_UNPACKED_BYTES = 200 * 1024 * 1024

# The hub's forbidden_files check: any of these fails the submission.
FORBIDDEN: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_ed25519",
    "*.kdbx",
    ".git/*",
    ".hg/*",
    ".svn/*",
    ".ssh/*",
    ".aws/*",
    ".npmrc",
    ".pypirc",
    ".netrc",
)
# Compiled or native files: allowed, but the hub flags them for the reviewer.
COMPILED: tuple[str, ...] = ("*.so", "*.dll", "*.dylib", "*.exe", "*.bin")
# Left out silently: caches and editor files.
IGNORED_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"})
IGNORED_FILES: tuple[str, ...] = ("*.pyc", "*.pyo", ".DS_Store", "Thumbs.db", "*~", "*.swp")
TOP_LEVEL_FILES: tuple[str, ...] = ("pyproject.toml", "README*", "CHANGELOG*", "LICENSE*", "NOTICE*")
TREES: tuple[str, ...] = ("src", "assets")


class PackError(ValueError):
    """The package cannot be built; the message lists what to fix."""


@dataclass
class Contents:
    files: dict[str, Path] = field(default_factory=dict)  # archive name -> file on disk
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def matches(name: str, patterns: Sequence[str]) -> bool:
    """A path matches "x/*" when it is anywhere under a folder x, other patterns by its base name (the hub's rule)."""
    base, padded = name.rsplit("/", 1)[-1], "/" + name
    for pattern in patterns:
        if pattern.endswith("/*"):
            if "/" + pattern[:-1] in padded:
                return True
        elif fnmatch.fnmatchcase(base, pattern):
            return True
    return False


def _walk(root: Path, folder: Path) -> Iterable[Path]:
    for path in sorted(folder.iterdir()):
        if path.is_dir() and not path.is_symlink():
            if path.name in IGNORED_DIRS:
                continue
            yield from _walk(root, path)
        else:
            yield path


def collect(project: Path, manifest: Manifest) -> Contents:
    """Every file that goes into the package of `project`, with what is wrong."""
    contents = Contents()
    project = project.resolve()

    def add(path: Path, required: bool = False) -> None:
        if not path.exists() and not path.is_symlink():
            if required:
                contents.errors.append(f"{path.relative_to(project).as_posix()} does not exist.")
            return
        name = path.relative_to(project).as_posix()
        if matches(name, FORBIDDEN):
            contents.errors.append(f"{name} must not be in a package (secrets or repository data).")
            return
        if path.is_symlink():
            contents.errors.append(f"{name} is a symbolic link; packages hold plain files only.")
            return
        if not stat.S_ISREG(path.stat().st_mode):
            contents.errors.append(f"{name} is not a plain file.")
            return
        if matches(name, IGNORED_FILES) or any(part.startswith(".") for part in name.split("/")):
            return
        if matches(name, COMPILED):
            contents.warnings.append(f"{name} is compiled or native code; the hub flags it for the reviewer.")
        contents.files[name] = path

    add(project / MANIFEST_NAME, required=True)
    for pattern in TOP_LEVEL_FILES:
        for path in sorted(project.glob(pattern)):
            if path.is_file():
                add(path)
    for relative in [manifest.long_description_file, manifest.icon, *manifest.screenshots]:
        if relative:
            add(project / relative, required=True)
    for tree in TREES:
        folder = project / tree
        if folder.is_dir():
            for path in _walk(project, folder):
                add(path)
    if not any(name.startswith("src/") for name in contents.files):
        contents.errors.append("src/ is empty: the plugin's code (and a theme's files) go there.")
    if len(contents.files) > MAX_PACKAGE_FILES:
        contents.errors.append(f"More than {MAX_PACKAGE_FILES} files.")
    total = sum(path.stat().st_size for path in contents.files.values())
    if total > MAX_UNPACKED_BYTES:
        contents.errors.append(f"The files add up to more than {MAX_UNPACKED_BYTES // (1024 * 1024)} MB.")
    return contents


def build(files: dict[str, Path], *, compress: bool = False) -> bytes:
    """The archive of `files` (archive name -> path), byte for byte the same for the same files."""
    buffer = io.BytesIO()
    method = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(buffer, "w", compression=method) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = method
            info.create_system = 3  # Unix, so the permission bits below are read
            info.external_attr = FILE_MODE << 16
            archive.writestr(
                info, files[name].read_bytes(), compress_type=method, compresslevel=9 if compress else None
            )
    return buffer.getvalue()


@dataclass(frozen=True)
class Packed:
    path: Path
    sha256: str
    size: int
    files: int
    warnings: tuple[str, ...]


def package_name(manifest: Manifest) -> str:
    return f"{manifest.id}-{manifest.version}{EXTENSION}"


def pack(project: Path, manifest: Manifest, out_dir: Path | None = None, *, compress: bool = False) -> Packed:
    """Write dist/<id>-<version>.sudoo (or into `out_dir`); PackError lists what stops it."""
    contents = collect(project, manifest)
    if contents.errors:
        raise PackError("\n".join(contents.errors))
    data = build(contents.files, compress=compress)
    if len(data) > MAX_PACKAGE_BYTES:
        raise PackError(f"The package is larger than {MAX_PACKAGE_BYTES // (1024 * 1024)} MB.")
    target_dir = out_dir if out_dir is not None else project / "dist"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / package_name(manifest)
    target.write_bytes(data)
    return Packed(target, sha256_of(data), len(data), len(contents.files), tuple(contents.warnings))


def read_manifest(package: Path | bytes) -> Manifest:
    """The manifest inside a package (ValueError when there is none or it is not valid)."""
    source = io.BytesIO(package) if isinstance(package, bytes) else package
    try:
        with zipfile.ZipFile(source) as archive:
            try:
                info = archive.getinfo(MANIFEST_NAME)
            except KeyError:
                raise ValueError("The package has no manifest.json at its root.") from None
            with archive.open(info) as fh:
                return parse_manifest(fh.read(64 * 1024 + 1))
    except zipfile.BadZipFile:
        raise ValueError("The file is not a .sudoo package (ZIP).") from None
