# Changelog

All notable changes to the Sudoo.sh plugin SDK. Versions follow [semver](https://semver.org): before 1.0.0 a minor
version may change an interface; from 1.0.0 only a major version does. A plugin's `sdk_version` in manifest.json
says which SDK versions it was written for.

## 0.1.0 - unreleased

First version, published on PyPI as `sudoo-plugin-sdk` (`pip install sudoo-plugin-sdk`).

- Packaging: complete PyPI metadata (licence expression `Apache-2.0`, project links, classifiers, `py.typed`) and a
  `publish.yml` workflow that builds the wheel and source archive on a GitHub release and uploads them to PyPI with
  trusted publishing and attestations (see RELEASING.md).

- `manifest`: the plugin manifest v1, a port of the hub's model with the same rules (14 permissions, `requires`,
  paid plugins, settings), and its JSON Schema (identical to `https://hub.sudoo.sh/schemas/plugin-manifest-v1.json`).
- `PluginContext` (settings, services, logger, data folder, the plugin's own storage, secrets and mail),
  `Caller`, `ServiceError` and the Protocols of the panel's service layer.
- `SudooPlugin` with the lifecycle hooks `on_install`, `on_enable`, `on_disable`, `on_uninstall`.
- Interfaces of the eight groups the panel loads today (exposure, add-on sources, update triggers, storage,
  authenticators, second factors, mailers, rate limiters) and of the groups planned for Sudoo.sh 2.0 (backups,
  notifications, instance hooks, dashboard widgets, web pages, background tasks, themes, API access, API routes,
  MCP, extensions).
- `Theme`: a tokens file checked against the panel's token names (light and dark, contrast), a logo SVG checked
  for scripts and outside references, and an e-mail accent.
- `sudoo-plugin` command: `new`, `validate`, `test`, `pack` (reproducible .sudoo packages), `verify` (the hub's
  Ed25519 statement), `publish` (the hub's developer endpoint, with `--dry-run`), `schema`, `types`.
- `sudoo_plugin_sdk.testing`: a fake panel (services, storage, secrets, mail) and pytest fixtures.
