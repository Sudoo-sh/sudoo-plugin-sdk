"""Entry-point groups: where the panel looks for each kind of plugin, and what each kind usually needs.

A manifest's `type` names one kind of plugin; its `entry_points` must then include that kind's group. Eight groups
exist in the panel today; the others are planned for the plugin manager of Sudoo.sh 2.0 and their interfaces may
still change before SDK 1.0.
"""

from __future__ import annotations

from dataclasses import dataclass

from sudoo_plugin_sdk.manifest import PLUGIN_TYPES


@dataclass(frozen=True)
class Group:
    type: str  # the manifest `type`
    name: str  # the entry-point group
    interface: str  # the class or Protocol in this SDK
    available: bool  # True: the panel loads it today; False: planned
    needs: frozenset[str] = frozenset()  # permissions a plugin of this group cannot work without
    usually: frozenset[str] = frozenset()  # permissions most plugins of this group ask for (a hint, not a rule)
    description: str = ""


GROUPS: tuple[Group, ...] = (
    Group("auth", "sudoo.auth", "Authenticator", True, usually=frozenset({"network.outbound"}),
          description="Checks a user name and password (LDAP, a company directory)"),
    Group("second_factor", "sudoo.second_factors", "SecondFactor", True,
          description="Proves it is really that person after the password (SMS, hardware keys)"),
    Group("mailer", "sudoo.mailers", "Mailer", True, usually=frozenset({"network.outbound"}),
          description="Sends the panel's e-mail (SMTP, an e-mail service's API)"),
    Group("exposure", "sudoo.exposure", "Exposure", True, usually=frozenset({"docker", "network.outbound"}),
          description="Turns a local port into an address people can open (tunnels, reverse proxies)"),
    Group("update_trigger", "sudoo.update_triggers", "UpdateTrigger", True, usually=frozenset({"network.inbound"}),
          description="Tells the panel that an instance has new code (webhooks, polling)"),
    Group("addon_source", "sudoo.addon_sources", "AddonSource", True,
          usually=frozenset({"filesystem.read", "network.outbound"}),
          description="Provides the Odoo Enterprise add-ons of each version"),
    Group("storage", "sudoo.storage", "Storage", True, description="Keeps the panel's own data (another database)"),
    Group("rate_limiter", "sudoo.rate_limiters", "RateLimiter", True,
          description="Keeps request counts (shared between panels)"),
    Group("backup", "sudoo.backups", "BackupDestination", False, needs=frozenset({"network.outbound"}),
          usually=frozenset({"instances.read"}), description="Stores backups elsewhere (S3, SFTP)"),
    Group("notification", "sudoo.notifications", "NotificationChannel", False,
          usually=frozenset({"network.outbound"}), description="Sends alerts to a channel (Slack, Discord, SMS)"),
    Group("instance_hook", "sudoo.instance_hooks", "InstanceHook", False, needs=frozenset({"instances.read"}),
          description="Runs when an instance is created, started, stopped or deleted"),
    Group("dashboard_widget", "sudoo.dashboard_widgets", "DashboardWidget", False,
          description="Adds a card to the dashboard"),
    Group("web_page", "sudoo.web_pages", "WebPage", False, description="Adds a page to the web app"),
    Group("background_task", "sudoo.background_tasks", "BackgroundTask", False,
          description="Runs recurring work in the background"),
    Group("theme", "sudoo.themes", "Theme", False, description="Changes the panel's colours, logo and e-mail accent"),
    Group("api", "sudoo.api_access", "ApiAccess", False, needs=frozenset({"network.inbound"}),
          description="Authenticates callers that are not the browser app (API tokens)"),
    Group("mcp", "sudoo.mcp", "McpServer", False, needs=frozenset({"network.inbound"}),
          description="Serves the panel's operations to Model Context Protocol clients"),
    Group("extension", "sudoo.extensions", "Extension", False, description="Anything else"),
)  # fmt: skip

# Groups a plugin may register beside its main one, without a `type` of their own.
EXTRA_GROUPS: dict[str, Group] = {
    "sudoo.api_blueprints": Group(
        "extension",
        "sudoo.api_blueprints",
        "ApiRoutes",
        False,
        needs=frozenset({"network.inbound"}),
        description="Adds endpoints under /api/v1/plugins/<id>/",
    ),
}

BY_TYPE: dict[str, Group] = {group.type: group for group in GROUPS}
BY_NAME: dict[str, Group] = {group.name: group for group in GROUPS} | EXTRA_GROUPS

assert set(BY_TYPE) == set(PLUGIN_TYPES)  # noqa: S101 - every manifest type has a group

# A theme is data: colours, a logo and an e-mail accent. It never needs a permission.
THEME_PERMISSIONS: frozenset[str] = frozenset()


def group_of(plugin_type: str) -> Group:
    return BY_TYPE[plugin_type]
