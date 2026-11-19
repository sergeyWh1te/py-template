from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest


class MetricsHandler:
    """Serves the app's own registry.

    A plain route rather than ``prometheus_client.make_asgi_app`` mounted at
    ``/metrics``: a Starlette ``Mount`` answers ``/metrics`` with a redirect to
    ``/metrics/``, which some scrapers do not follow.
    """

    def __init__(self, registry: CollectorRegistry) -> None:
        self._registry = registry

    async def handle(self) -> Response:
        return Response(content=generate_latest(self._registry), media_type=CONTENT_TYPE_LATEST)
