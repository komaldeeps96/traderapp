"""Application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.rest import router as api_router
from .api.ws import websocket_endpoint
from .core.logging import setup_logging
from .core.settings import BACKEND_ROOT, Settings, get_settings
from .services.container import AppContainer, set_container

logger = logging.getLogger(__name__)

FRONTEND_DIST = BACKEND_ROOT.parent / "frontend" / "dist"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    Accepting settings here is what lets the integration tests construct a
    complete, real app — same routes, same services — pointed at a stubbed
    upstream instead of the live market.
    """
    resolved = settings or get_settings()
    setup_logging(resolved.log_level)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        container = AppContainer(resolved)
        set_container(container)
        await container.start()
        try:
            yield
        finally:
            await container.stop()
            set_container(None)

    app = FastAPI(title=resolved.app_name, version="1.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        # Private-network origins on the same two ports, so the terminal opens
        # on a phone or tablet over the home WiFi. Empty means laptop-only.
        allow_origin_regex=resolved.cors_origin_regex or None,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket_endpoint(websocket)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built UI from the API server when it has been built.

    Mounted last so it never shadows /api or /ws. In development the frontend
    runs on its own Vite server instead and this does nothing.
    """
    index = FRONTEND_DIST / "index.html"
    if not index.exists():
        return
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
    logger.info("Serving frontend from %s", FRONTEND_DIST)


app = create_app()


def main() -> None:
    import uvicorn  # noqa: PLC0415 — only needed when run as a script

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
