from __future__ import annotations

"""Sprint 6 REST API application."""

import logging
from pathlib import Path

from ._compat import CORSMiddleware, FastAPI
from .state import APP_START
from .routers.companies import router as companies_router
from .routers.clusters import router as clusters_router
from .routers.health import router as health_router
from .routers.peers import router as peers_router
from .routers.screener import router as screener_router
from .routers.sectors import router as sectors_router

PROJECT_ROOT = Path(__file__).resolve().parents[2]

LOGGER = logging.getLogger(__name__)
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)

app = FastAPI(title="Nifty 100 Analytics API", version="6.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def _include_router(router: object) -> None:
    app.include_router(router, prefix="/api/v1")


_include_router(companies_router)
_include_router(screener_router)
_include_router(sectors_router)
_include_router(peers_router)
_include_router(clusters_router)
_include_router(health_router)


def _log_request(method: str, path: str, status_code: int, duration: float) -> None:
    LOGGER.info("%s %s -> %s in %.3fs", method, path, status_code, duration)


app.request_logger = _log_request  # type: ignore[attr-defined]


__all__ = ["app", "APP_START", "_log_request"]
