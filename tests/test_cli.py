from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from sudoo_plugin_sdk.cli import main
from sudoo_plugin_sdk.publish import PublishError, changelog_entry, hub_url, publish
from tests.conftest import ProjectFactory


def test_new_validate_test_pack(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "alerts"
    assert main(["new", "notification", "com.example.alerts", "--dir", str(target), "--author", "Ann"]) == 0
    assert json.loads((target / "manifest.json").read_text())["author"] == {"name": "Ann"}
    assert main(["validate", str(target)]) == 0
    assert main(["validate", str(target), "--strict"]) == 1  # planned-group warning
    assert main(["test", str(target), "--", "-q", "-p", "no:cacheprovider"]) == 0
    assert main(["pack", str(target)]) == 0
    out = capsys.readouterr().out
    assert "sha256 " in out and "com.example.alerts-0.1.0.sudoo" in out


def test_new_refuses_bad_input(tmp_path: Path) -> None:
    assert main(["new", "theme", "Not An Id", "--dir", str(tmp_path / "x")]) == 1
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "f").write_text("x")
    assert main(["new", "theme", "com.example.full", "--dir", str(tmp_path / "full")]) == 1
    with pytest.raises(SystemExit):
        main(["new", "rootkit", "com.example.x"])


def test_pack_stops_on_errors(make_project: ProjectFactory, capsys: pytest.CaptureFixture[str]) -> None:
    project = make_project("theme", permissions=["docker"])
    assert main(["pack", str(project)]) == 1
    assert "Not packed" in capsys.readouterr().err
    assert not (project / "dist").exists()


def test_schema_and_types(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema"]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "Sudoo plugin manifest v1"
    assert main(["types"]) == 0
    assert "sudoo.themes" in capsys.readouterr().out


def test_publish_dry_run(make_project: ProjectFactory, capsys: pytest.CaptureFixture[str]) -> None:
    project = make_project("theme", plugin_id="com.example.dry-theme")
    assert main(["publish", str(project), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Dry run" in out and "First version." in out
    package = project / "dist" / "com.example.dry-theme-0.1.0.sudoo"
    assert main(["publish", str(package), "--dry-run", "--changelog", "Darker sidebar."]) == 0
    assert main(["publish", str(package), "--dry-run"]) == 0  # CHANGELOG.md found above dist/


def test_publish_needs_a_changelog_and_a_token(make_project: ProjectFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    project = make_project("theme")
    (project / "CHANGELOG.md").write_text("# Changelog\n")
    assert main(["publish", str(project), "--dry-run"]) == 1
    monkeypatch.delenv("SUDOO_DEVELOPER_TOKEN", raising=False)
    assert main(["publish", str(project), "--changelog", "x"]) == 1


def _hub(known: list[str], seen: list[httpx.Request], status: int = 201) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["authorization"] == "Bearer test-token"
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": plugin} for plugin in known]})
        if status >= 400:
            return httpx.Response(status, json={"title": "Invalid", "detail": "The manifest is not valid.",
                                                "errors": [{"field": "manifest.version", "message": "bad"}]})  # fmt: skip
        return httpx.Response(status, json={"data": {"status": "awaiting_review", "checks": [
            {"name": "package_size", "status": "passed", "message": "ok"}]}})  # fmt: skip

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_publish_new_plugin_and_new_version(make_project: ProjectFactory) -> None:
    project = make_project("theme", plugin_id="com.example.sent-theme")
    assert main(["pack", str(project)]) == 0
    package = project / "dist" / "com.example.sent-theme-0.1.0.sudoo"

    seen: list[httpx.Request] = []
    result = publish(package, "First.", hub="https://hub.example.test", token="test-token", client=_hub([], seen))
    assert result.new_plugin is True
    assert seen[1].url.path == "/api/v1/developer/plugins"
    body = seen[1].content
    assert b'name="manifest"' in body and b'name="package"' in body and b'name="changelog"' in body
    assert b"com.example.sent-theme" in body

    seen.clear()
    result = publish(
        package,
        "Second.",
        hub="https://hub.example.test",
        token="test-token",
        client=_hub(["com.example.sent-theme"], seen),
    )
    assert result.new_plugin is False
    assert seen[1].url.path == "/api/v1/developer/plugins/com.example.sent-theme/versions"
    assert result.response is not None and result.response["data"]["status"] == "awaiting_review"


def test_publish_reports_the_hubs_refusal(make_project: ProjectFactory) -> None:
    project = make_project("theme", plugin_id="com.example.refused-theme")
    assert main(["pack", str(project)]) == 0
    package = project / "dist" / "com.example.refused-theme-0.1.0.sudoo"
    with pytest.raises(PublishError, match=r"(?s)422.*manifest.version: bad"):
        publish(package, "x", hub="https://hub.example.test", token="test-token", client=_hub([], [], status=422))


def test_hub_address_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUDOO_HUB_URL", raising=False)
    assert hub_url(None) == "https://hub.sudoo.sh"
    assert hub_url("http://localhost:8000/") == "http://localhost:8000"
    with pytest.raises(PublishError):
        hub_url("http://hub.example.test")


def test_changelog_entry(tmp_path: Path) -> None:
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## [1.1.0] - 2026-11-01\n\n- B\n\n## 1.0.0\n\n- A\n")
    assert changelog_entry(tmp_path, "1.1.0") == "- B"
    assert changelog_entry(tmp_path, "1.0.0") == "- A"
    assert changelog_entry(tmp_path, "2.0.0") is None
