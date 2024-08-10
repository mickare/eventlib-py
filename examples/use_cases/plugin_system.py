# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Example of loading and starting plugins with dependencies between them.
"""

from dataclasses import dataclass
from typing import Protocol

from eventlib import BaseEvent


class Plugin(Protocol):
    """Basic plugin interface in this example."""

    name: str

    def load(self):
        """Load the plugin."""

    def start(self):
        """Start the plugin."""


@dataclass
class PluginEvent(BaseEvent):
    """Event that occurs when any change to a plugin occurs."""

    plugin: Plugin


class PluginLoadedEvent(PluginEvent):
    """A plugin was loaded."""


class PluginStartedEvent(PluginEvent):
    """A plugin was started"""


# ==================================================================================================
# Another package (registered in Python's plugin system)


class CorePlugin(Plugin):
    """Example core plugin."""

    def load(self):
        print("Core loaded")

    def start(self):
        print("Core started")


# ==================================================================================================
# Another package (registered in Python's plugin system)
class MyPlugin(Plugin):
    """Example plugin."""

    def load(self):
        PluginStartedEvent.subscribe()(self._on_plugin_started)
        print("MyPlugin loaded")

    def _on_plugin_started(self, event: PluginStartedEvent):
        if isinstance(event.plugin, CorePlugin):
            print("Core is avaliable")

    def start(self):
        print("MyPlugin started")


# ==================================================================================================
# Example
def plugin_example():
    """Plugin system example."""
    plugins = [MyPlugin(), CorePlugin()]
    # Load plugins
    for plugin in plugins:
        plugin.load()
        PluginLoadedEvent(plugin).emit()
    # Start plugins
    for plugin in plugins:
        plugin.start()
        PluginStartedEvent(plugin).emit()


if __name__ == "__main__":
    plugin_example()
