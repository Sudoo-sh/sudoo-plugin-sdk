"""Tests of package signing and verification."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sudoo_plugin_sdk.cli import main
from sudoo_plugin_sdk.signing import (
    generate_private_key,
    key_id,
    load_public_key,
    public_key_b64url,
    public_key_pem,
    sha256_of,
    sign_package,
    signing_message,
    verify_package,
)
from tests.conftest import ProjectFactory

# Made with the hub's own hub.signing.sign_package (Ed25519 signatures are deterministic): private key bytes 0..31,
# package b"sudoo test vector package", plugin com.example.vector 1.2.3.
VECTOR_KEY = bytes(range(32))
VECTOR_PACKAGE = b"sudoo test vector package"
VECTOR_SIGNATURE = "UfJzr1VoauxgLxDiKDOz0vGT0A5Y0FWDEzJyclA82CweaH9Es08cN-C8h20XKjoIEsdbMcT0dfbVBw3M5wB3Ag"
VECTOR_KEY_ID = "56475aa75463474c"
VECTOR_SHA256 = "a736f3b91c02ed6a2d66659087d6c43ba83b2627408434736f54ab52de5d6ad5"
VECTOR_PUBLIC = "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg"


def test_the_statement_format() -> None:
    """Test: the statement format."""
    assert signing_message("com.example.x", "1.0.0", "a" * 64) == b"sudoo-plugin-v1\ncom.example.x\n1.0.0\n" + b"a" * 64
    with pytest.raises(ValueError):
        signing_message("com.example.x\n", "1.0.0", "a" * 64)
    with pytest.raises(ValueError):
        signing_message("com.example.x", "1.0.0", "A" * 64)
    with pytest.raises(ValueError):
        signing_message("com.example.x", "1.0.0", "a" * 64 + "\n")


def test_matches_the_hubs_signature() -> None:
    """Test: matches the hubs signature."""
    key = Ed25519PrivateKey.from_private_bytes(VECTOR_KEY)
    signed = sign_package(key, "com.example.vector", "1.2.3", VECTOR_PACKAGE)
    assert (signed.signature, signed.key_id, signed.sha256) == (VECTOR_SIGNATURE, VECTOR_KEY_ID, VECTOR_SHA256)
    assert public_key_b64url(key.public_key()) == VECTOR_PUBLIC
    public = load_public_key(VECTOR_PUBLIC.encode())
    assert verify_package(public, "com.example.vector", "1.2.3", VECTOR_PACKAGE, VECTOR_SIGNATURE, VECTOR_SHA256)


def test_round_trip_and_tampering(tmp_path: Path) -> None:
    """Test: round trip and tampering."""
    key = generate_private_key()
    package = tmp_path / "p.sudoo"
    package.write_bytes(b"PK package bytes")
    signed = sign_package(key, "com.example.p", "1.0.0", package)
    public = load_public_key(public_key_pem(key.public_key()))
    assert key_id(public) == signed.key_id
    assert verify_package(public, "com.example.p", "1.0.0", package, signed.signature)
    assert verify_package(public, "com.example.p", "1.0.0", package, signed.signature, signed.sha256.upper())
    assert not verify_package(public, "com.example.other", "1.0.0", package, signed.signature)
    assert not verify_package(public, "com.example.p", "0.9.0", package, signed.signature)
    assert not verify_package(public, "com.example.p", "1.0.0", package, signed.signature, "0" * 64)
    assert not verify_package(public, "com.example.p", "1.0.0", package, "not base64!")
    assert not verify_package(public, "com.example.p", "1.0.0", package, signed.signature[:20])
    other = generate_private_key().public_key()
    assert not verify_package(other, "com.example.p", "1.0.0", package, signed.signature)
    package.write_bytes(b"PK package bytes, changed")
    assert not verify_package(public, "com.example.p", "1.0.0", package, signed.signature)


def test_sha256_of_sources(tmp_path: Path) -> None:
    """Test: sha256 of sources."""
    path = tmp_path / "f"
    path.write_bytes(b"abc")
    assert sha256_of(b"abc") == sha256_of(path) == sha256_of(iter([b"a", b"bc"]))


def test_bad_public_keys() -> None:
    """Test: bad public keys."""
    with pytest.raises(ValueError):
        load_public_key(b"AAAA")
    with pytest.raises(ValueError):
        load_public_key(b"not a key!")


def test_cli_verify(make_project: ProjectFactory, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test: cli verify."""
    project = make_project("theme", "com.example.signed-theme")
    assert main(["pack", str(project)]) == 0
    package = project / "dist" / "com.example.signed-theme-0.1.0.sudoo"
    key = generate_private_key()
    signed = sign_package(key, "com.example.signed-theme", "0.1.0", package)
    key_file = tmp_path / "hub.pub"
    key_file.write_bytes(public_key_pem(key.public_key()))
    (tmp_path / "sig").write_text(signed.signature)
    Path(str(package) + ".sig").write_text(signed.signature + "\n")
    capsys.readouterr()

    assert main(["verify", str(package), "--public-key", str(key_file)]) == 0
    assert "Verified: com.example.signed-theme 0.1.0" in capsys.readouterr().out
    raw = public_key_b64url(key.public_key())
    assert main(["verify", str(package), f"--public-key={raw}", "--signature-file", str(tmp_path / "sig")]) == 0
    assert (
        main(
            ["verify", str(package), f"--public-key={raw}", "--signature", signed.signature, "--sha256", signed.sha256]
        )
        == 0
    )

    wrong = public_key_b64url(generate_private_key().public_key())
    assert main(["verify", str(package), f"--public-key={wrong}"]) == 1
    assert "NOT VERIFIED" in capsys.readouterr().err
    assert main(["verify", str(package), "--public-key", "nonsense!"]) == 1
