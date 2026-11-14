# Graph Report - sudoo-plugin-sdk  (2026-11-14)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 745 nodes · 1745 edges · 33 communities (15 shown, 18 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 100 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- cli.py
- manifest.py
- Caller
- plugins/__init__.py
- pytest
- theme.py
- Manifest
- signing.py
- test_validate.py
- ci.yml
- Services
- google-updates.json
- test_cli.py
- Resource
- context.py
- SudooPlugin
- Exposure
- SecondFactor
- PluginSettings
- Storage
- core.py
- AddonSource
- PluginStorage
- RouteInfo
- UpdateTrigger
- Protocol
- Mailer
- EventService
- Secrets
- sudoo-plugin-sdk

## God Nodes (most connected - your core abstractions)
1. `Caller` - 68 edges
2. `Manifest` - 39 edges
3. `validate()` - 22 edges
4. `_need()` - 22 edges
5. `ServiceError` - 21 edges
6. `FakeInstances` - 19 edges
7. `FakeServices` - 19 edges
8. `load_manifest()` - 19 edges
9. `pack()` - 19 edges
10. `make_context()` - 19 edges

## Surprising Connections (you probably didn't know these)
- `test_forbidden_files_stop_the_build()` --uses--> `PackError`  [INFERRED]
  tests/test_package.py → src/sudoo_plugin_sdk/package.py
- `test_links_are_refused()` --uses--> `PackError`  [INFERRED]
  tests/test_package.py → src/sudoo_plugin_sdk/package.py
- `test_missing_declared_files()` --uses--> `PackError`  [INFERRED]
  tests/test_package.py → src/sudoo_plugin_sdk/package.py
- `test_hub_address_rules()` --uses--> `PublishError`  [INFERRED]
  tests/test_cli.py → src/sudoo_plugin_sdk/publish.py
- `test_publish_reports_the_hubs_refusal()` --uses--> `PublishError`  [INFERRED]
  tests/test_cli.py → src/sudoo_plugin_sdk/publish.py

## Import Cycles
- None detected.

## Communities (33 total, 18 thin omitted)

### Community 0 - "cli.py"
Cohesion: 0.07
Nodes (41): cmd_new(), cmd_pack(), cmd_publish(), cmd_schema(), cmd_test(), cmd_types(), cmd_validate(), cmd_verify() (+33 more)

### Community 1 - "manifest.py"
Cohesion: 0.06
Nodes (31): load_manifest(), ManifestError, parse_manifest(), build(), collect(), add(), Contents, matches() (+23 more)

### Community 2 - "Caller"
Cohesion: 0.10
Nodes (16): Caller, ServiceError, Call, FakeBackups, FakeDocs, FakeEvents, FakeInstances, FakeJobs (+8 more)

### Community 3 - "plugins/__init__.py"
Cohesion: 0.05
Nodes (18): AccessRefused, ApiAccess, ApiRequest, ApiResponse, ApiRoutes, BackgroundTask, BackupDestination, DashboardWidget (+10 more)

### Community 4 - "pytest"
Cohesion: 0.08
Nodes (19): FakeServices, make_context(), MemorySecrets, MemoryStorage, person(), fake_services(), find_project(), memory_storage() (+11 more)

### Community 5 - "theme.py"
Cohesion: 0.08
Nodes (26): _check_contrast(), check_email_accent(), check_logo_svg(), check_tokens_css(), contrast(), _declarations(), _external_url(), _local() (+18 more)

### Community 6 - "Manifest"
Cohesion: 0.08
Nodes (17): Author, Manifest, _relative_path(), Requirement, semver_key(), _semver_key(), Setting, test_duplicate_setting_keys_are_refused() (+9 more)

### Community 7 - "signing.py"
Cohesion: 0.11
Nodes (18): b64url(), from_b64url(), generate_private_key(), key_id(), load_public_key(), PackageSignature, public_key_b64url(), public_key_pem() (+10 more)

### Community 8 - "test_validate.py"
Cohesion: 0.13
Nodes (15): copy_tree(), make_project(), factory(), _errors(), test_a_theme_asks_for_no_permission(), test_every_scaffold_validates(), test_import_failures_and_missing_methods(), test_invalid_manifest_fields_are_named() (+7 more)

### Community 9 - "ci.yml"
Cohesion: 0.07
Nodes (26): runs-on, steps, strategy, timeout-minutes, concurrency, cancel-in-progress, group, jobs (+18 more)

### Community 10 - "Services"
Cohesion: 0.10
Nodes (6): BackupService, DocsService, Mail, ServerService, Services, VersionService

### Community 11 - "google-updates.json"
Cohesion: 0.10
Nodes (20): last_verified, policy, $schema, _schema_doc, unverified[], updates[], secondary_sources, source_of_truth (+12 more)

### Community 12 - "test_cli.py"
Cohesion: 0.19
Nodes (12): main(), _hub(), test_changelog_entry(), test_hub_address_rules(), test_new_refuses_bad_input(), test_new_validate_test_pack(), test_pack_stops_on_errors(), test_publish_dry_run() (+4 more)

### Community 20 - "core.py"
Cohesion: 0.25
Nodes (3): Decision, MailError, RateLimiter

### Community 23 - "RouteInfo"
Cohesion: 0.32
Nodes (3): RouteInfo, RouteService, FakeRoutes

## Knowledge Gaps
- **1 isolated node(s):** `sudoo-plugin-sdk`
  These have ≤1 connection - possible missing edges. (Counts symbols only; 229 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **18 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Caller` connect `Caller` to `plugins/__init__.py`, `pytest`, `Services`, `Resource`, `context.py`?**
  _High betweenness centrality (0.129) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `Caller` (e.g. with `ApiAccess` and `BackgroundTask`) actually correct?**
  _`Caller` has 13 INFERRED edges - model-reasoned connections that need verification._
- **What connects `sudoo-plugin-sdk` to the rest of the system?**
  _1 weakly-connected nodes found - possible missing edges._
- **Should `cli.py` be split into smaller, more focused modules?**
  _Cohesion score 0.0716297786720322 - nodes in this community are weakly interconnected._
- **Why does `Manifest` connect `Manifest` to `cli.py`, `manifest.py`, `Caller`, `pytest`, `context.py`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Are the 21 inferred relationships involving `Manifest` (e.g. with `collect()` and `pack()`) actually correct?**
  _`Manifest` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Should `manifest.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06351236146632566 - nodes in this community are weakly interconnected._