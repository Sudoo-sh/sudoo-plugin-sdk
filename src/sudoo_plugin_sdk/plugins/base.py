"""The base class of every plugin: created once with a PluginContext, told about its own lifecycle.

    install -> enable -> (disable -> enable)* -> uninstall

The panel calls the hooks in that order. Each hook may be called again after a failure, so make it safe to repeat.
A hook that raises stops that step and the panel shows the message to the administrator.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from sudoo_plugin_sdk.context import PluginContext, PluginSettings


class SudooPlugin:
    """Subclass this and implement the interface of your plugin's group (see sudoo_plugin_sdk.plugins)."""

    #: Permissions the class needs at least; `sudoo-plugin validate` checks the manifest asks for them.
    required_permissions: ClassVar[frozenset[str]] = frozenset()

    def __init__(self, context: PluginContext) -> None:
        self.context = context

    @property
    def settings(self) -> PluginSettings:
        return self.context.settings

    @property
    def logger(self) -> logging.Logger:
        return self.context.logger

    def on_install(self) -> None:
        """After the package is verified and unpacked: create tables, folders, defaults."""

    def on_enable(self) -> None:
        """When the administrator turns the plugin on (and at each start of the panel while it is on)."""

    def on_disable(self) -> None:
        """When it is turned off, or a paid licence ended: stop threads, keep all data."""

    def on_uninstall(self) -> None:
        """Before the files are removed: delete what the plugin made outside its data folder. The panel has taken a
        backup first."""
