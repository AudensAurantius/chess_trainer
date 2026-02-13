"""FastAPI application factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__
from ..config import AppConfig
from .auth import AuthMiddleware, auth_router
from .routes import router
from .session_manager import SessionManager

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATE_DIR = Path(__file__).parent / "templates"


def create_app(config: AppConfig) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: Application configuration.

    Returns:
        Configured FastAPI instance.
    """
    auth_store = None

    # Auth setup (only when enabled)
    if config.auth.enabled:
        from ..auth.service import AuthService
        from ..auth.store import AuthStore

        auth_store = AuthStore(config.auth.database_path)
        _ = auth_store.conn  # Force schema init

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if auth_store is not None:
            auth_store.close()

    app = FastAPI(title="Chess Trainer", version=__version__, lifespan=lifespan)

    # Store config and session manager in app state
    app.state.config = config
    app.state.session_manager = SessionManager(config)
    app.state.templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

    if config.auth.enabled and auth_store is not None:
        from ..auth.service import AuthService

        auth_service = AuthService(auth_store, config.auth.session_expiry_hours)
        app.state.auth_store = auth_store
        app.state.auth_service = auth_service

    # Auth middleware runs on every request (no-op when auth disabled)
    app.add_middleware(AuthMiddleware)

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Include auth routes before main routes
    app.include_router(auth_router)
    app.include_router(router)

    return app
