"""Ed25519 signatures of plugin packages, the hub's scheme (hub.sudoo.sh, ROADMAP section 12).

The hub signs a package after review. What it signs is not the file alone but a statement binding the file to the
plugin and version it is published as:

    sudoo-plugin-v1\\n<plugin id>\\n<version>\\n<sha256 of the package, hex>

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

DOMAIN = b"sudoo-plugin-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ED25519_PUBLIC_BYTES = 32
ED25519_SIGNATURE_BYTES = 64
_CHUNK = 1024 * 1024
_B64URL = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=")


@dataclass(frozen=True)
class PackageSignature:
    signature: str  # base64url of the 64-byte Ed25519 signature
    key_id: str  # which key made it
    sha256: str


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def from_b64url(text: str) -> bytes:
    """Decode base64url with or without padding; ValueError when it is not base64url."""
    if not text or any(c not in _B64URL for c in text):
        raise ValueError("not base64url")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as error:
        raise ValueError("not base64url") from error


def key_id(key: Ed25519PublicKey) -> str:
    """A short name for a public key: the first 16 hex digits of the SHA-256 of its raw bytes."""
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def sha256_of(source: bytes | Path | Iterable[bytes]) -> str:
    """SHA-256 (hex) of bytes, of a file (read in chunks) or of a stream of chunks."""
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
    if not SHA256_RE.match(sha256):
        raise ValueError("sha256 must be 64 lower-case hex digits")
    if not plugin_id or not version or any(c in plugin_id + version for c in "\n\r\0"):
        raise ValueError("plugin id and version must be single-line and not empty")
    return b"\n".join((DOMAIN, plugin_id.encode(), version.encode(), sha256.encode()))


def sign_package(
    private_key: Ed25519PrivateKey, plugin_id: str, version: str, package: bytes | Path
) -> PackageSignature:
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
    """True only when `signature` is a signature of this package as this plugin and version (and, when given,
    the package's SHA-256 is `expected_sha256`, as listed in the catalogue)."""
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
    return Ed25519PrivateKey.generate()


def public_key_pem(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def public_key_b64url(key: Ed25519PublicKey) -> str:
    return b64url(key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def load_public_key(data: bytes) -> Ed25519PublicKey:
    """An Ed25519 public key from PEM or from base64url of its 32 raw bytes."""
    if b"-----BEGIN" in data:
        key = serialization.load_pem_public_key(data)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("the key is not an Ed25519 public key")
        return key
    raw = from_b64url(data.decode().strip())
    if len(raw) != ED25519_PUBLIC_BYTES:
        raise ValueError("an Ed25519 public key is 32 bytes")
    return Ed25519PublicKey.from_public_bytes(raw)
