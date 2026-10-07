"""A broken plugin must not break the client, but must not fail silently either.
See docs/bugs/09-minor-issues.md (9b).
"""

import logging

import pytest

from myelin.plugins import (
    apply_client_methods,
    apply_plugin_methods,
    get_manager,
    hookimpl,
    load_plugin_classes,
)


class BrokenPlugin:
    @hookimpl
    def client_load_classes(self, client):
        raise ImportError("no such Java class")

    @hookimpl
    def client_methods(self, client):
        return {"process": lambda self: "plugin"}


class ConflictingPlugin:
    @hookimpl
    def client_methods(self, client):
        return {"process": lambda self: "other plugin"}


class Client:
    pass


@pytest.fixture
def plugins():
    pm = get_manager()
    registered = [BrokenPlugin(), ConflictingPlugin()]
    for plugin in registered:
        pm.register(plugin)
    yield
    for plugin in registered:
        pm.unregister(plugin)


def test_failed_class_hook_is_logged_not_raised(plugins, caplog):
    with caplog.at_level(logging.WARNING, logger="myelin.plugins.manager"):
        load_plugin_classes(Client())
    (record,) = caplog.records
    assert "client_load_classes failed for Client" in record.getMessage()
    assert record.exc_info is not None


def test_conflicting_methods_are_logged_not_raised(plugins, caplog):
    with pytest.raises(RuntimeError, match="Conflicting plugin methods"):
        apply_client_methods(Client())

    client = Client()
    with caplog.at_level(logging.WARNING, logger="myelin.plugins.manager"):
        apply_plugin_methods(client)
    (record,) = caplog.records
    assert "client_methods failed for Client" in record.getMessage()
    assert not hasattr(client, "process")
