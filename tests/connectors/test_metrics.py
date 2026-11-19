import platform

from prometheus_client import CollectorRegistry, generate_latest

from app_template.connectors import metrics


def test_metric_prefix_replaces_dashes_and_spaces() -> None:
    assert metrics.metric_prefix("py-template") == "py_template"
    assert metrics.metric_prefix("my  app-name") == "my_app_name"


def test_build_info_is_registered_in_the_app_registry() -> None:
    registry = CollectorRegistry()
    store = metrics.new(registry, "py-template", "test", "abc123")

    store.build_info.inc()

    value = registry.get_sample_value(
        "py_template_metric_build_info_total",
        {"name": "py-template", "env": "test", "commit": "abc123", "version": platform.python_version()},
    )
    assert value == 1.0


def test_runtime_collectors_are_registered() -> None:
    registry = CollectorRegistry()
    metrics.new(registry, "app", "test", "")

    exposition = generate_latest(registry).decode()

    assert "python_info" in exposition
    assert "python_gc_objects_collected_total" in exposition
