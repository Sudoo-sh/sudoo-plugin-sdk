# Sudoo.sh plugin SDK

[![CI](https://github.com/Sudoo-sh/sudoo-plugin-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/Sudoo-sh/sudoo-plugin-sdk/actions/workflows/ci.yml)
[![Licence: Apache-2.0](https://img.shields.io/badge/licence-Apache--2.0-informational)](https://github.com/Sudoo-sh/sudoo-plugin-sdk/blob/main/LICENSE.md)
[![PyPI](https://img.shields.io/pypi/v/sudoo-plugin-sdk)](https://pypi.org/project/sudoo-plugin-sdk/)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-informational)

Everything needed to build a plugin for [Sudoo.sh](https://sudoo.sh), the self-hosted panel that runs a live Odoo
for every Git branch on your own server:

- **Manifest types**: `manifest.json` as a pydantic model with exactly the hub's rules, and its JSON Schema.
- **Plugin interfaces**: a typed interface for every entry-point group, the `SudooPlugin` base class with its
  lifecycle hooks, `PluginContext` (settings, services, logger, data folder) and the `Theme` class.
- **A test harness**: a fake panel (services, settings, storage, secrets, mail) and pytest fixtures, so a plugin
  is tested without a panel.
- **The `sudoo-plugin` command**: `new`, `validate`, `test`, `pack`, `verify`, `publish`.

| | |
| :--- | :--- |
| Package | `sudoo-plugin-sdk` (import `sudoo_plugin_sdk`), version 0.1.1 |
| Command | `sudoo-plugin` |
| Python | 3.12 or newer (CI runs 3.12 and 3.14) |
| Depends on | pydantic, email-validator, cryptography, httpx; pytest for `sudoo-plugin test` (extra `test`) |
| Talks to | hub.sudoo.sh (`publish` only) |
| Template | [sudoo-plugin-template](https://github.com/Sudoo-sh/sudoo-plugin-template): a working theme and a notification channel, with CI and a release workflow |

## Contents

1. [Licence](#licence)
2. [Install](#install)
3. [Quick start](#quick-start)
4. [The command](#the-command)
5. [The manifest](#the-manifest)
6. [The package (.sudoo)](#the-package-sudoo)
7. [Writing a plugin](#writing-a-plugin)
8. [Themes](#themes)
9. [Testing](#testing)
10. [Signatures](#signatures)
11. [Publishing and review](#publishing-and-review)
12. [Environment variables](#environment-variables)
13. [Security notes](#security-notes)
14. [Working on the SDK](#working-on-the-sdk)
15. [Links](#links)

---

## Licence

The SDK is released under the **Apache License 2.0**
([LICENSE.md](https://github.com/Sudoo-sh/sudoo-plugin-sdk/blob/main/LICENSE.md)). It is permissive, so the code of
a third-party plugin that imports it is not encumbered: you may license your plugin as you like, open or closed,
free or paid. It also grants a patent licence from every contributor and keeps the Sudoo.sh name, logo and badges out of
the grant (trademarks). The panel and the hub are under their own licences.

## Install

The SDK is published on [PyPI](https://pypi.org/project/sudoo-plugin-sdk/):

```bash
pip install sudoo-plugin-sdk
# with the test harness (`sudoo-plugin test` and the pytest fixtures):
pip install "sudoo-plugin-sdk[test]"
```

**In a plugin's `pyproject.toml` (the default in the template)**

```toml
[project]
dependencies = ["sudoo-plugin-sdk>=0.1.0,<1.0.0"]

[dependency-groups]
dev = ["sudoo-plugin-sdk[test]>=0.1.0,<1.0.0", "pytest>=9.2.0"]
```

**From Git (an unreleased commit)**

```toml
[tool.uv.sources]
sudoo-plugin-sdk = { git = "https://github.com/Sudoo-sh/sudoo-plugin-sdk" }
```

**From a local checkout (developing the SDK and a plugin together)**

```bash
# without touching the plugin's pyproject.toml:
uv run --no-project --with-editable "../sudoo-plugin-sdk[test]" sudoo-plugin test
# or point the source at the folder:
#   [tool.uv.sources]
#   sudoo-plugin-sdk = { path = "../sudoo-plugin-sdk", editable = true }
```

`sudoo-plugin validate`, `test` and `pack` read the plugin from its `src/` folder, so they work without
installing the plugin itself.

**As a tool**

```bash
uv tool install "sudoo-plugin-sdk[test]"   # or: pipx install "sudoo-plugin-sdk[test]"
sudoo-plugin --version
```

## Quick start

```bash
sudoo-plugin new theme com.example.midnight-theme   # or: uv run --with ... sudoo-plugin new ...
cd midnight-theme
uv sync
uv run sudoo-plugin validate
uv run sudoo-plugin test
uv run sudoo-plugin pack          # dist/com.example.midnight-theme-0.1.0.sudoo and its SHA-256
```

Most developers start from the [template repository](https://github.com/Sudoo-sh/sudoo-plugin-template) instead:
it has the same layout plus CI and a release workflow.

## The command

| Command | Does |
| :--- | :--- |
| `sudoo-plugin new <type> <id> [--dir D] [--author NAME]` | A new project from the built-in templates. Every type gets a class with all the methods of its interface; a theme gets a starter palette and logo. The result validates, tests and packs as it is. |
| `sudoo-plugin validate [path] [--strict] [--no-import]` | What the hub's automated checks look at (below). `--strict` fails on warnings; `--no-import` skips importing the code. |
| `sudoo-plugin test [path] [-- pytest args]` | Validates, then runs `tests/` with pytest against the fake panel (the SDK's fixtures are loaded automatically). |
| `sudoo-plugin pack [path] [--out D] [--compress]` | Validates, then writes `dist/<id>-<version>.sudoo` and prints its SHA-256. The same sources always give the same bytes. |
| `sudoo-plugin verify <package> --public-key K [--signature S \| --signature-file F] [--sha256 H]` | Checks the hub's Ed25519 signature of a package for the plugin id and version in its manifest. `K` is a PEM file or the base64url key from `GET https://hub.sudoo.sh/api/v1/keys`; the signature defaults to `<package>.sig`. |
| `sudoo-plugin publish [path \| package] [--changelog T \| --changelog-file F] [--hub URL] [--dry-run]` | Packs (when given a folder) and uploads to the hub's developer endpoint with `SUDOO_DEVELOPER_TOKEN`. The changelog defaults to this version's section of `CHANGELOG.md`. `--dry-run` checks and shows what would be sent, and sends nothing. |
| `sudoo-plugin schema` | The manifest's JSON Schema. |
| `sudoo-plugin types` | Plugin types, their entry-point groups, interfaces and required permissions, and the 14 permissions. |

Exit status: 0 success, 1 a check or command failed, 2 wrong usage.

### What `validate` checks

| Check | Error when | Warning when |
| :--- | :--- | :--- |
| Manifest | it breaks a rule of the hub's model (each field is named, as the hub names it) | `sdk_version` does not include this SDK |
| Structure | a forbidden file would be packed (`.env`, keys, `.git/`, `.ssh/` ...), a link or special file, a declared icon or screenshot is missing, `src/` is empty, the hub's size or file limits are exceeded | compiled or native files; no README, LICENSE, CHANGELOG, `tests/` or `pyproject.toml` |
| Groups | the `type`'s group is not in `entry_points`; a group the panel does not know | the group is planned for Sudoo.sh 2.0 |
| Permissions | a group's required permission is missing; a theme asks for any permission; a class's `required_permissions` are not asked for | a permission most plugins of the group need; `network.inbound` with nothing serving requests; `docker` |
| pyproject.toml | its `sudoo.*` entry points or its version differ from `manifest.json` | |
| Code | an entry point does not import, is not a class, lives outside `src/`, or lacks a method of its interface; a theme fails the theme checks | |
| Scan | | the hub's static scan finds `eval`, `exec`, `os.system`, `subprocess`, `pickle.load`, `__import__` |

## The manifest

`manifest.json` at the root of the project, validated with the hub's own rules (`sudoo_plugin_sdk.manifest` is a
port of the hub's model; a test keeps its JSON Schema identical to the hub's).

```json
{
  "$schema": "https://hub.sudoo.sh/schemas/plugin-manifest-v1.json",
  "id": "com.example.webhook-alerts",
  "name": "Webhook alerts",
  "version": "1.0.0",
  "sdk_version": ">=0.1.0,<1.0.0",
  "min_sudoo_version": "2.0.0",
  "author": {"name": "Example Ltd", "email": "plugins@example.com", "url": "https://example.com"},
  "description": "Posts the panel's alerts to a chat webhook.",
  "long_description_file": "README.md",
  "license": "MIT",
  "type": "notification",
  "tags": ["alerts", "webhook"],
  "entry_points": {"sudoo.notifications": {"webhook-alerts": "example_webhook_alerts.plugin:WebhookAlerts"}},
  "settings": [{"key": "webhook_url", "type": "secret", "label": "Webhook address"}],
  "permissions": ["network.outbound"],
  "requires": [],
  "tier": "free"
}
```

| Field | Rule |
| :--- | :--- |
| `id` | Reverse domain, lower case, 3 to 7 parts: `com.example.webhook-alerts` |
| `version`, `min_sudoo_version`, `max_sudoo_version` | semver (`1.2.0`, `2.0.0-rc.1`); max not lower than min |
| `sdk_version` | A specifier: `>=0.1.0,<1.0.0` |
| `type` | One of `auth`, `second_factor`, `mailer`, `exposure`, `update_trigger`, `addon_source`, `storage`, `rate_limiter`, `backup`, `notification`, `instance_hook`, `dashboard_widget`, `web_page`, `background_task`, `theme`, `api`, `mcp`, `extension` |
| `entry_points` | `{"sudoo.<group>": {"<name>": "module.path:Class"}}`, at least one, and the same as `[project.entry-points]` in `pyproject.toml` |
| `settings` | `string`, `integer`, `number`, `boolean`, `secret` (never a default) or `choice` (with `choices`); keys unique |
| `permissions` | Each at most once, from the 14 below |
| `requires` | Other plugins: `"com.sudoo.api"` or `{"id": "com.sudoo.api", "version": ">=1.0.0,<2.0.0"}`; never itself, never twice |
| `tier`, `price` | `free` without a price, or `paid` with a price in cents (100 to 1,000,000) |
| `license` | An SPDX expression (`MIT`, `Apache-2.0`, `MIT OR Apache-2.0`) |
| `icon`, `screenshots`, `long_description_file` | Paths inside the package (no `..`, no leading `/`) |
| `homepage`, `issues` | https addresses |
| `signature` | Always `null`: the hub's signature travels next to the package |

Unknown fields are refused. **Permissions**: `network.inbound`, `network.outbound`, `instances.read`,
`instances.write`, `accounts.read`, `settings.read`, `settings.write`, `storage.read`, `storage.write`,
`filesystem.read`, `filesystem.write`, `secrets`, `mail.send`, `docker` (`sudoo-plugin types` prints what each
allows). The panel shows them to the administrator before installing; reviewers check each is needed.

## The package (.sudoo)

A ZIP archive with `manifest.json` at its root, plus `pyproject.toml`, `README*`, `CHANGELOG*`, `LICENSE*`, the
manifest's icon, screenshots and long description, everything under `src/` and `assets/`. Tests, caches
(`__pycache__`, `.pyc`) and hidden files are left out; secrets and repository data stop the build.

It is **reproducible**: entries sorted by path, every timestamp 1980-01-01 00:00, permissions 0644, no directory
entries or extra fields, and entries stored rather than compressed (so the bytes do not depend on the zlib build).
Anyone can rebuild a tag and compare the SHA-256 with the one the hub lists. `--compress` deflates the entries
(smaller, reproducible with the same zlib).

## Writing a plugin

A plugin is a class registered under an entry-point group. The panel creates it once with a `PluginContext` and
calls the methods of its group's interface.

```python
from sudoo_plugin_sdk import SudooPlugin
from sudoo_plugin_sdk.plugins import Notification


class WebhookAlerts(SudooPlugin):
    name = "webhook-alerts"
    label = "Webhook alerts"
    events: frozenset[str] = frozenset()        # all events

    @property
    def ready(self) -> bool:
        return bool(self.settings.string("webhook_url"))

    def send(self, notification: Notification) -> None:
        ...                                     # POST to the webhook; raise RuntimeError with a sentence on failure

    def on_enable(self) -> None:                # lifecycle hooks: on_install, on_enable, on_disable, on_uninstall
        self.logger.info("Alerts go to the configured webhook.")
```

### PluginContext

| Attribute | What it is |
| :--- | :--- |
| `settings` | The values of the manifest's settings (defaults until the administrator changes them): `settings.string(key)`, `.integer`, `.number`, `.boolean`, or `settings[key]` |
| `services` | The panel's service layer: `instances`, `jobs`, `backups`, `versions`, `docs`, `server`, `events`, `routes`. Every call takes a `Caller`, checks its permissions and is audited |
| `caller` | The plugin's own `Caller` (`plugin:<id>`), for work it does by itself; it may do what its granted permissions allow (`instances.read` lets it view instances and logs, `instances.write` also change them) |
| `logger` | A `logging.Logger` whose lines appear in the panel's log |
| `data_dir` | A folder only this plugin writes to; kept across updates, removed on uninstall |
| `storage`, `secrets`, `mail` | The plugin's own records, the encrypted vault and the panel's mailer; present only with `storage.read`/`storage.write`, `secrets`, `mail.send` |
| `permissions`, `require(permission)` | What was granted at install |

A plugin never reads environment variables, imports Flask or reaches into the panel's modules: everything comes
through the context. A service refuses with `ServiceError(status, title, detail)`.

### Every group

| Type | Group | Interface (`sudoo_plugin_sdk.plugins`) | Panel | Required permissions |
| :--- | :--- | :--- | :--- | :--- |
| `auth` | `sudoo.auth` | `Authenticator`: `manages_passwords`, `authenticate(username, password) -> Identity \| None` | today | |
| `second_factor` | `sudoo.second_factors` | `SecondFactor`: `challenge`, `verify`, `begin_setup`, `finish_setup`, `remove`, `enrolled`, `available` | today | |
| `mailer` | `sudoo.mailers` | `Mailer`: `ready`, `send(to, subject, text, html)` raising `MailError` | today | |
| `exposure` | `sudoo.exposure` | `Exposure`: `ensure`, `remove`, `address`, `instance_ports`, `panel_env`, `listen_host`, `https`, `client_ip_header` | today | |
| `update_trigger` | `sudoo.update_triggers` | `UpdateTrigger`: `start(request_update)`, `blueprint()` | today | |
| `addon_source` | `sudoo.addon_sources` | `AddonSource`: `available(version)`, `prepare(version, log) -> Path` | today | |
| `storage` | `sudoo.storage` | `Storage`: `get`, `all`, `put`, `delete`, `change`, `log`, `logs` | today | |
| `rate_limiter` | `sudoo.rate_limiters` | `RateLimiter`: `hit(key, limit, window_seconds) -> Decision` | today | |
| `backup` | `sudoo.backups` | `BackupDestination`: `upload`, `list`, `download`, `delete` | 2.0 | `network.outbound` |
| `notification` | `sudoo.notifications` | `NotificationChannel`: `ready`, `send(Notification)`, `events` | 2.0 | |
| `instance_hook` | `sudoo.instance_hooks` | `InstanceHook`: `events`, `handle(event, instance, log)` | 2.0 | `instances.read` |
| `dashboard_widget` | `sudoo.dashboard_widgets` | `DashboardWidget`: `render(caller) -> Widget \| None`, `refresh_seconds` | 2.0 | |
| `web_page` | `sudoo.web_pages` | `WebPage`: `pages() -> [PageInfo]` (pre-built JS bundles in `src/`) | 2.0 | |
| `background_task` | `sudoo.background_tasks` | `BackgroundTask`: `run(caller)`, `interval_seconds` | 2.0 | |
| `theme` | `sudoo.themes` | `Theme` (a class to subclass, see [Themes](#themes)) | 2.0 | none allowed |
| `api` | `sudoo.api_access` | `ApiAccess`: `authenticate(ApiRequest) -> Caller \| None`, `routes()`, `permissions()` | 2.0 | `network.inbound` |
| `mcp` | `sudoo.mcp` | `McpServer`: `handle(request, caller)` | 2.0 | `network.inbound` |
| `extension` | `sudoo.extensions` | `Extension`: lifecycle hooks and `context.services` only | 2.0 | |
| (any) | `sudoo.api_blueprints` | `ApiRoutes`: `routes()` under `/api/v1/plugins/<id>/` | 2.0 | `network.inbound` |

"today" groups mirror the panel's `src/sudoo/*/base.py` method for method (without Flask types). The 2.0 groups
are this SDK's proposal for the plugin manager of Sudoo.sh 2.0 and may change before SDK 1.0; `validate` warns
when you use one. `sudoo-plugin new <type> <id>` writes a class with every method of the interface.

Rules that the review checks (from the panel's [plugin rules](https://docs.sudoo.sh)): refuse bad settings in the
constructor or `on_enable` with a sentence naming the setting; make `ensure`-like calls safe to repeat; run
commands as argument lists, never through a shell; type everything.

## Themes

A theme changes the panel's colours, its logo and the accent of its e-mails, and nothing else. It asks for no
permission and contains no logic.

```python
from sudoo_plugin_sdk import Theme


class Midnight(Theme):
    label = "Midnight"
    tokens = "tokens.css"       # next to this module, in src/
    logo = "logo.svg"           # optional
    email_accent = "#3d4fb8"    # optional, #RRGGBB
```

```json
"type": "theme",
"entry_points": {"sudoo.themes": {"midnight": "example_midnight_theme.plugin:Midnight"}},
"permissions": []
```

**The tokens file** may contain only these rules:

```css
:root { --accent: #3d4fb8; --on-accent: #ffffff; }                      /* light */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { --accent: #9aa8ff; --on-accent: #0d1024; }   /* dark, system */
}
:root[data-theme="dark"] { --accent: #9aa8ff; --on-accent: #0d1024; }    /* dark, chosen in the panel */
@media (prefers-contrast: more) { :root { ... } }                         /* optional */
@media (prefers-reduced-transparency: reduce) { :root { ... } }           /* optional */
```

Both dark rules are required and must be identical, as in the panel's own `_tokens.scss`. Tokens a theme may set:

| Group | Tokens |
| :--- | :--- |
| Accent | `--accent`, `--accent-ink`, `--on-accent`, `--accent-soft`, `--accent-ring` |
| Neutrals | `--bg`, `--surface`, `--raised`, `--hairline`, `--hairline-strong`, `--text`, `--text-2`, `--text-3`, `--overlay` |
| Meaning | `--positive`, `--negative`, `--caution`, `--working`, `--idle` |
| Charts | `--series-1`, `--series-2`, `--series-grid` |
| Type faces | `--font`, `--mono` (system or already shipped faces; a theme cannot load font files) |
| Shape | `--radius-tag`, `--radius-control`, `--radius-card`, `--radius-panel`, `--shadow-small`, `--shadow-float` |
| Materials | `--material`, `--material-blur` |

Spacing (`--s1` to `--s12`), layout (`--sidebar`, `--topbar`), type sizes (`--text-12` to `--text-32`) and motion
(`--ease*`, `--press`, `--quick`, `--menu`, `--enter`, `--sheet`) stay the panel's, so a theme cannot break layouts
or the reduced-motion behaviour. Values may not use `url()`, `image()`, `expression`, `@import`, backslashes or
`var()` of names that are not panel tokens.

**Contrast** (WCAG 2): `--text` on `--bg` and `--surface`, and `--on-accent` on `--accent`, must reach 4.5:1 in
light and in dark (an error otherwise); `--text-2`, `--text-3`, `--accent-ink` on `--surface` and `--text` on
`--raised` below 4.5:1 are warnings. Tokens a theme leaves out keep the panel's values, and are checked with them.

**The logo** is an SVG with a `viewBox`, at most 64 KB, made of SVG shapes, text, gradients, clips, masks and
simple filters with presentation attributes (`fill`, `stroke`, ...) only: no `<script>`, `<style>`, `style`
attributes, `<foreignObject>`, `<image>`, `<a>`, animations, event handlers (`on*`), elements outside the SVG
namespace, editor attributes, comments, CDATA, DOCTYPE or entities, and no reference outside the file (`href` and
`url()` only as `#id`). The SDK refuses an unsafe file rather than rewriting it.

**The e-mail accent** is `#RRGGBB` (the panel's `BRAND_COLOR` format); a warning when white button text on it is
below 4.5:1.

`Theme.check()` returns all of this as a report, so a theme's tests can assert `Midnight.check().errors == []`.

## Testing

```python
from sudoo_plugin_sdk.context import PluginContext
from sudoo_plugin_sdk.plugins import Notification
from sudoo_plugin_sdk.testing import FakeServices, make_context, person

from example_webhook_alerts.plugin import WebhookAlerts


def test_sends(sudoo_context: PluginContext) -> None:          # fixture: the manifest's id, defaults, permissions
    plugin = WebhookAlerts(sudoo_context)
    ...


def test_with_settings(tmp_path) -> None:
    services = FakeServices()
    services.instances.add("sales-main", branch="main", version="19.0")
    context = make_context("com.example.webhook-alerts", settings={"webhook_url": "https://hooks.example.test/x"},
                           permissions={"network.outbound", "instances.read"}, services=services, data_dir=tmp_path)
    assert services.instances.get(context.caller, "sales-main")["branch"] == "main"
    assert [(c.service, c.method) for c in services.calls] == [("instances", "get")]
```

| Fixture | Gives |
| :--- | :--- |
| `sudoo_project`, `sudoo_manifest` | The plugin folder and its validated manifest |
| `sudoo_context` | A `PluginContext` from the manifest, with `fake_services` and a data folder under `tmp_path` |
| `fake_services` | `FakeServices`: instances, jobs, backups, versions, docs, server figures, events (`emit`) and routes in memory; permissions checked like the panel (403 `ServiceError`), every call recorded in `calls` |
| `memory_storage` | The context's `MemoryStorage` (when the manifest asks for storage) |

`person("instances.view", ...)` builds the `Caller` of someone signed in; `MemorySecrets` and `Outbox` (the mailer,
with `messages`) complete the fake panel.

## Signatures

The hub signs a package after review. The signature (Ed25519, base64url) covers the statement

```
sudoo-plugin-v1
<plugin id>
<version>
<sha256 of the package, hex>
```

so a signed package cannot be passed off as another plugin or another version. Panels refuse unsigned or tampered
packages. `sudoo-plugin verify` checks a downloaded package the same way; `sudoo_plugin_sdk.signing` has the same
functions as the hub (`sign_package` exists for tests and private hubs; developers never sign what they publish).

## Publishing and review

```bash
export SUDOO_DEVELOPER_TOKEN=sdk_...        # a developer API token from developers.sudoo.sh (Settings, API tokens)
uv run sudoo-plugin publish --dry-run       # what would be sent
uv run sudoo-plugin publish                 # packs and uploads; prints the state and the automated checks
```

`publish` sends `manifest`, `package` and `changelog` (multipart) to `POST /api/v1/developer/plugins/<id>/versions`
with `Authorization: Bearer sdk_...`. A developer API token can do only that, for your own plugins, so it is safe to
keep as a CI secret; it is shown once when made, and you can give it an expiry and revoke it. A plugin's **first**
version is submitted on developers.sudoo.sh (Plugins, New plugin); after that, `publish` and the release workflow
send every new version. (A short-lived sign-in token from the console also works and can create a new plugin.) Then:

1. **Automated checks** (seconds): manifest, `requires`, package structure and size, file paths, forbidden files,
   permissions against entry points, the static scan, the licence field. A failure sends the version back with the
   report; `validate` runs the same checks before you upload.
2. **Test install and review**: a reviewer installs it on a review panel with sample Odoo data, exercises its
   settings, and checks it does what the listing says, asks only for the permissions it needs, sends no data away
   without saying so, works in light and dark, has docs and a working support contact.
3. **Published**: the hub signs the package and lists it on marketplace.sudoo.sh.

Every version is reviewed by a person today. Follow the state, the check results and the reviewer's messages on
developers.sudoo.sh.

## Environment variables

| Variable | Used by | Meaning |
| :--- | :--- | :--- |
| `SUDOO_DEVELOPER_TOKEN` | `publish` | Your developer token; never passed as an argument, so it stays out of shell history and logs |
| `SUDOO_HUB_URL` | `publish` | Another hub (default `https://hub.sudoo.sh`; `http://` only for `localhost`) |

## Security notes

- `validate` and `test` **import your plugin's code**, as the panel will; run them on code you trust (yours).
  `validate --no-import` checks everything that does not need the code.
- `pack` refuses secrets and repository data and never follows links (a linked file or folder stops the build);
  it writes only into `dist/` (or `--out`).
- `publish` sends the token only to the hub address, over https, and does not follow redirects.
- Theme files are data: the token parser accepts custom properties of known names only, and logos are checked
  against an allow-list of SVG elements and attributes, so they cannot run scripts or load anything from elsewhere. XML is parsed only after DOCTYPE and entities are
  refused.

## Working on the SDK

```bash
uv sync                 # Python 3.14 (see .python-version) and the dev tools, from uv.lock
uv run ruff check .     # lint
uv run black --check .  # format
uv run mypy             # types (strict)
uv run pytest           # tests
uv build                # wheel and source archive
```

Releases are published to PyPI by `.github/workflows/publish.yml`; see
[RELEASING.md](https://github.com/Sudoo-sh/sudoo-plugin-sdk/blob/main/RELEASING.md).

Keep `manifest.py` in step with the hub (`src/hub/schemas/manifest.py`). When the hub's model changes, port the
change and refresh `tests/data/hub-manifest-schema.json` from the hub
(`uv run python -c "import json; from hub.schemas.manifest import json_schema; print(json.dumps(json_schema(), indent=2, sort_keys=True))"`).
The theme token list is compared with the panel's `web/src/styles/_tokens.scss` when a checkout of the panel sits
next to this one.

### Formatting

Code is formatted with black and linted with ruff (settings in `pyproject.toml`; ruff also sorts imports), and mypy
checks the types. Run `uv run black .` to rewrite files and `uv run black --check .` to check them without changes.
The same checks run on every commit with pre-commit (run `uvx pre-commit install` once).

## Links

| | |
| :--- | :--- |
| Product | [sudoo.sh](https://sudoo.sh) |
| Documentation | [docs.sudoo.sh](https://docs.sudoo.sh) |
| Marketplace | [marketplace.sudoo.sh](https://marketplace.sudoo.sh) |
| Developers | [developers.sudoo.sh](https://developers.sudoo.sh) |
| Account | [app.sudoo.sh](https://app.sudoo.sh) |
| Hub API | [hub.sudoo.sh](https://hub.sudoo.sh) |
| Status | [status.sudoo.sh](https://status.sudoo.sh) |
| Panel source | [github.com/Sudoo-sh/sudoo.sh](https://github.com/Sudoo-sh/sudoo.sh) |
| Plugin template | [github.com/Sudoo-sh/sudoo-plugin-template](https://github.com/Sudoo-sh/sudoo-plugin-template) |

© 2026 Sudoo.sh
