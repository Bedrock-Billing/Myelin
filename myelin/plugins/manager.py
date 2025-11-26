import importlib.metadata
import types
from typing import Any, Callable

import pluggy

from .hookspecs import project_name

_plugin_manager: pluggy.PluginManager | None = None


def get_manager() -> pluggy.PluginManager:
    global _plugin_manager
    if _plugin_manager is None:
        pm = pluggy.PluginManager(project_name)
        pm.add_hookspecs(importlib.import_module("myelin.plugins.hookspecs"))
        # Load entry points lazily
        for ep in importlib.metadata.entry_points().select(group=project_name):
            try:
                pm.load_setuptools_entrypoints(name=ep.name, group=project_name)
            except Exception:
                # Ignore malformed entry points
                pass
        _plugin_manager = pm
    return _plugin_manager


def register(plugin: Any) -> None:
    get_manager().register(plugin)


def run_client_load_classes(client: Any) -> None:
    pm = get_manager()
    pm.hook.client_load_classes(client=client)


def apply_client_methods(client: Any) -> None:
    if getattr(client, "_plugins_applied", False):
        return
    pm = get_manager()
    results = pm.hook.client_methods(client=client)
    merged: dict[str, Callable[..., Any]] = {}
    for result in results:
        if not result:
            continue
        for name, func in result.items():
            if name in merged:
                raise RuntimeError(f"Conflicting plugin methods for client: {name}")
            merged[name] = func
    for name, func in merged.items():
        bound = types.MethodType(func, client)
        setattr(client, name, bound)
    setattr(client, "_plugins_applied", True)
