r"""Ed25519 signatures of plugin packages, the hub's scheme (hub.sudoo.sh, ROADMAP section 12).

The hub signs a package after review. What it signs is not the file alone but a statement binding the file to the
plugin and version it is published as:

    sudoo-plugin-v1\n<plugin id>\n<version>\n<sha256 of the package, hex>

so a validly signed package cannot be passed off as another plugin, or as another version of the same one. The
signature is base64url (no padding) of the 64 signature bytes; public keys are PEM or base64url of their 32 raw
bytes (GET https://hub.sudoo.sh/api/v1/keys). `sign_package` exists for tests and for private hubs: plugin
developers never sign what they publish, the hub does.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

# The first line of every signed statement. It keeps these signatures apart from any other use of the key.
DOMAIN = b"sudoo-plugin-v1"
# Pattern of a SHA-256 value written as 64 lower-case hex digits.
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# Length of a raw Ed25519 public key, in bytes.
ED25519_PUBLIC_BYTES = 32
# Length of an Ed25519 signature, in bytes.
ED25519_SIGNATURE_BYTES = 64
# Size of the pieces a file is read in when its SHA-256 is computed, in bytes (1 MB).
_CHUNK = 1024 * 1024
# The characters allowed in base64url text (with "=" for padding).
_B64URL = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=")


@dataclass(frozen=True)
class PackageSignature:
    """The result of signing a package.

    Attributes:
        signature: Base64url of the 64-byte Ed25519 signature.
        key_id: Which key made it (see `key_id`).
        sha256: The SHA-256 of the package, as hex.
    """

    signature: str  # base64url of the 64-byte Ed25519 signature
    key_id: str  # which key made it
    sha256: str


def b64url(data: bytes) -> str:
    """Encode bytes as base64url without padding.

    Args:
        data: The bytes to encode.

    Returns:
        The text.
    """
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def from_b64url(text: str) -> bytes:
    """Decode base64url with or without padding.

    Args:
        text: The base64url text.

    Returns:
        The decoded bytes.

    Raises:
        ValueError: When the text is empty or is not base64url.
    """
    if not text or any(c not in _B64URL for c in text):
        raise ValueError("not base64url")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as error:
        raise ValueError("not base64url") from error


def key_id(key: Ed25519PublicKey) -> str:
    """A short name for a public key: the first 16 hex digits of the SHA-256 of its raw bytes.

    Args:
        key: The public key.

    Returns:
        The 16-digit name.
    """
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def sha256_of(source: bytes | Path | Iterable[bytes]) -> str:
    """SHA-256 (hex) of bytes, of a file (read in chunks) or of a stream of chunks.

    Args:
        source: The bytes, the path of a file, or an iterable of byte chunks.

    Returns:
        The hash as 64 lower-case hex digits.
    """
    digest = hashlib.sha256()
    if isinstance(source, bytes):
        digest.update(source)
    elif isinstance(source, Path):
        with source.open("rb") as fh:
            while chunk := fh.read(_CHUNK):
                digest.update(chunk)
    else:
        for chunk in source:
            digest.update(chunk)
    return digest.hexdigest()


def signing_message(plugin_id: str, version: str, sha256: str) -> bytes:
    """Build the statement that is signed: the domain line, the plugin id, the version and the package's hash, one per line.

    Args:
        plugin_id: The plugin's id.
        version: The version it is published as.
        sha256: The package's SHA-256 as 64 lower-case hex digits.

    Returns:
        The statement as bytes, without a final newline.

    Raises:
        ValueError: When the hash is not 64 lower-case hex digits, or the id or version is empty or has a line break.
    """
    if not SHA256_RE.fullmatch(sha256):
        raise ValueError("sha256 must be 64 lower-case hex digits")
    if not plugin_id or not version or any(c in plugin_id + version for c in "\n\r\0"):
        raise ValueError("plugin id and version must be single-line and not empty")
    return b"\n".join((DOMAIN, plugin_id.encode(), version.encode(), sha256.encode()))


def sign_package(
    private_key: Ed25519PrivateKey, plugin_id: str, version: str, package: bytes | Path
) -> PackageSignature:
    """Sign a package as a plugin and version. For tests and private hubs only.

    Args:
        private_key: The signing key.
        plugin_id: The plugin's id.
        version: The version the package is published as.
        package: The package bytes, or the path of the package file.

    Returns:
        The signature, the key's id and the package's SHA-256.
    """
    sha256 = sha256_of(package)
    signature = private_key.sign(signing_message(plugin_id, version, sha256))
    return PackageSignature(b64url(signature), key_id(private_key.public_key()), sha256)


def verify_package(
    public_key: Ed25519PublicKey,
    plugin_id: str,
    version: str,
    package: bytes | Path,
    signature: str,
    expected_sha256: str | None = None,
) -> bool:
    """True only when `signature` is a signature of this package as this plugin and version.

    When `expected_sha256` is given, the package's SHA-256 must also equal it, as listed in the catalogue.

    Args:
        public_key: The key to check with.
        plugin_id: The plugin's id.
        version: The version the package is published as.
        package: The package bytes, or the path of the package file.
        signature: The base64url signature.
        expected_sha256: The hash the catalogue lists, or None to skip that check.

    Returns:
        True when the signature is valid, False in every other case (including a badly formed signature).
    """
    sha256 = sha256_of(package)
    if expected_sha256 is not None and not hmac.compare_digest(sha256, expected_sha256.strip().lower()):
        return False
    try:
        raw = from_b64url(signature.strip())
    except ValueError:
        return False
    if len(raw) != ED25519_SIGNATURE_BYTES:
        return False
    try:
        public_key.verify(raw, signing_message(plugin_id, version, sha256))
    except InvalidSignature:
        return False
    return True


def generate_private_key() -> Ed25519PrivateKey:
    """Make a new Ed25519 private key.

    Returns:
        The key.
    """
    return Ed25519PrivateKey.generate()


def public_key_pem(key: Ed25519PublicKey) -> bytes:
    """Write a public key as PEM.

    Args:
        key: The public key.

    Returns:
        The PEM bytes (SubjectPublicKeyInfo).
    """
    return key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def public_key_b64url(key: Ed25519PublicKey) -> str:
    """Write a public key as base64url of its 32 raw bytes.

    Args:
        key: The public key.

    Returns:
        The text.
    """
    return b64url(key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def load_public_key(data: bytes) -> Ed25519PublicKey:
    """An Ed25519 public key from PEM or from base64url of its 32 raw bytes.

    Args:
        data: The key, as PEM or as base64url text in bytes.

    Returns:
        The public key.

    Raises:
        ValueError: When the data is not an Ed25519 public key.
    """
    if b"-----BEGIN" in data:
        key = serialization.load_pem_public_key(data)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("the key is not an Ed25519 public key")
        return key
    raw = from_b64url(data.decode().strip())
    if len(raw) != ED25519_PUBLIC_BYTES:
        raise ValueError("an Ed25519 public key is 32 bytes")
    return Ed25519PublicKey.from_public_bytes(raw)
