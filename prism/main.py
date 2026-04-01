"""PRISM FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from prism import __version__
from prism.config import settings
from prism.database import init_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    await init_db()
    logger.info("PRISM v%s started. DB: %s", __version__, settings.effective_db_url)
    yield
    logger.info("PRISM shutting down.")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title="PRISM — Shadow AI Traffic Analyzer",
        version=__version__,
        description=(
            "Active probe, PCAP analysis, and real-time AI traffic interception platform."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    from prism.api.tasks import router as tasks_router
    from prism.api.records import router as records_router
    from prism.api.certs import router as certs_router
    from prism.api.signatures import router as sig_router
    from prism.api.websocket import router as ws_router

    app.include_router(tasks_router)
    app.include_router(records_router)
    app.include_router(certs_router)
    app.include_router(sig_router)
    app.include_router(ws_router)

    # Serve built React frontend if present
    frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": __version__}

    return app


app = create_app()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    uvicorn.run(
        "prism.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )


if __name__ == "__main__":
    main()
