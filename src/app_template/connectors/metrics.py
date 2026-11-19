"""Prometheus registry for the app.

Everything registers into the app's *own* ``CollectorRegistry``, which is what
``/metrics`` serves. prometheus_client's default is the global ``REGISTRY``: a
metric created without ``registry=`` lands there, and since ``/metrics`` does not
serve it, the metric silently never appears. Always pass ``registry=``.
"""

import platform
import re
from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter
from prometheus_client.gc_collector import GCCollector
from prometheus_client.platform_collector import PlatformCollector
from prometheus_client.process_collector import ProcessCollector

_NON_METRIC_CHARS = re.compile(r"[-\s]+")


@dataclass(frozen=True, slots=True)
class Metrics:
    registry: CollectorRegistry
    # Exposed as `<prefix>_metric_build_info_total`: prometheus_client always
    # appends `_total` to counters in the text format (Go's client does not).
    build_info: Counter


def metric_prefix(app_name: str) -> str:
    return _NON_METRIC_CHARS.sub("_", app_name)


def new(registry: CollectorRegistry, app_name: str, env: str, commit: str) -> Metrics:
    # The global registry is never exposed, so the process/platform/GC collectors
    # must be registered here explicitly to show up at all. ProcessCollector reads
    # /proc and reports nothing on macOS — it fills in inside the Linux container.
    ProcessCollector(registry=registry)
    PlatformCollector(registry=registry)
    GCCollector(registry=registry)

    build_info = Counter(
        f"{metric_prefix(app_name)}_metric_build_info",
        "Build information",
        labelnames=["name", "env", "commit", "version"],
        registry=registry,
    ).labels(name=app_name, env=env, commit=commit, version=platform.python_version())

    return Metrics(registry=registry, build_info=build_info)
