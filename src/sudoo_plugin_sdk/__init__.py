"""The Sudoo.sh plugin SDK: manifest types, plugin interfaces, a test harness and the `sudoo-plugin` command.

from sudoo_plugin_sdk import SudooPlugin, PluginContext, Theme
from sudoo_plugin_sdk.plugins import NotificationChannel, Notification
from sudoo_plugin_sdk.testing import make_context
"""

__version__ = "0.1.1"

from sudoo_plugin_sdk.context import Caller, PluginContext, PluginSettings, ServiceError, Services
from sudoo_plugin_sdk.manifest import Manifest, load_manifest
from sudoo_plugin_sdk.plugins.base import SudooPlugin
from sudoo_plugin_sdk.theme import Theme

__all__ = [
    "Caller",
    "Manifest",
    "PluginContext",
    "PluginSettings",
    "ServiceError",
    "Services",
    "SudooPlugin",
    "Theme",
    "__version__",
    "load_manifest",
]
