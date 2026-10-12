"""
FastAPI application entry point, lifecycle lifespan binding, static routing, and CLI runner.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import api_router
from app.api.websocket import ws_router
from app.core.config import load_config
from app.core.lifecycle import get_lifecycle_manager
from app.core.logging_config import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager controlling application startup and teardown."""
    manager = get_lifecycle_manager()
    manager.startup()
    try:
        yield
    finally:
        manager.shutdown()


def create_app() -> FastAPI:
    """Create and configure FastAPI application instance."""
    config = load_config()
    setup_logging(config.server.log_level)

    app = FastAPI(
        title="Edge Vision Monitor",
        description="Production-grade YOLO11 edge AI inference and telemetry platform for Raspberry Pi 5 with Hailo-8L",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS for development flexibility
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routers
    app.include_router(api_router)
    app.include_router(ws_router)

    # Mount static assets
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/", include_in_schema=False)
        def serve_dashboard():
            index_path = static_dir / "index.html"
            if index_path.exists():
                return FileResponse(
                    index_path,
                    headers={
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache",
                        "Expires": "0",
                    },
                )
            return {"message": "Edge Vision Monitor API running. Dashboard assets missing."}

        @app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
        def serve_favicon():
            fav_path = static_dir / "favicon.svg"
            if fav_path.exists():
                return FileResponse(fav_path, media_type="image/svg+xml")
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()


def run():
    """CLI entry point for uvicorn server."""
    import uvicorn
    config = load_config()
    uvicorn.run(
        "app.main:app",
        host=config.server.host,
        port=config.server.port,
        log_level=config.server.log_level.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    run()
