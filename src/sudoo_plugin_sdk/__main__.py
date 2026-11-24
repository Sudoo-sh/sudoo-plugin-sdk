"""Entry point for `python -m sudoo_plugin_sdk`: runs the `sudoo-plugin` command and exits with its exit code."""

from sudoo_plugin_sdk.cli import main

raise SystemExit(main())
