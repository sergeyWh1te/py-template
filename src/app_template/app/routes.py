from fastapi import FastAPI

from app_template.app.usecase import Usecases
from app_template.connectors.metrics import Metrics
from app_template.http.handlers.health.handler import HealthHandler
from app_template.http.handlers.metrics.handler import MetricsHandler
from app_template.http.handlers.user_example.handler import UserExampleHandler
from app_template.http.middleware.access_log import AccessLogMiddleware
from app_template.http.middleware.recovery import RecoveryMiddleware
from app_template.http.middleware.request_id import RequestIDMiddleware
from app_template.http.middleware.timeout import TimeoutMiddleware
from app_template.utils.deps import Logger


def new_router() -> FastAPI:
    # No /docs, /redoc or /openapi.json: go-template exposes no API description
    # either, and an accidentally public schema is a needless leak. Pass the
    # *_url arguments to turn them on.
    return FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def register_routes(api: FastAPI, log: Logger, metrics: Metrics, usecases: Usecases) -> None:
    # add_middleware *prepends*: the last one added is the outermost. Read
    # bottom-up, a request passes RequestID -> AccessLog -> Recovery -> Timeout
    # -> route, so the access log sees the id and the final (recovered) status.
    api.add_middleware(TimeoutMiddleware, log=log)
    api.add_middleware(RecoveryMiddleware, log=log)
    api.add_middleware(AccessLogMiddleware, log=log)
    api.add_middleware(RequestIDMiddleware)

    api.add_api_route("/health", HealthHandler().handle, methods=["GET"])
    # The app's own registry — see connectors/metrics.py for why not the global one.
    api.add_api_route("/metrics", MetricsHandler(metrics.registry).handle, methods=["GET"])
    # usecases.user is typed as users.Usecase; the handler asks for its narrower
    # UserGetter protocol. mypy proves the two are compatible right here.
    api.add_api_route("/example", UserExampleHandler(log, usecases.user).handle, methods=["GET"])
