"""FastAPI application factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..config import AppConfig
from .auth import AuthMiddleware, auth_router
from .manager_pool import ManagerPool
from .routes import router

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

    pool = ManagerPool(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        pool.close_all()
        if auth_store is not None:
            auth_store.close()

    app = FastAPI(title="Chess Trainer", version=__version__, lifespan=lifespan)

    # Store config and manager pool in app state
    app.state.config = config
    app.state.manager_pool = pool
    app.state.templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

    if config.auth.enabled and auth_store is not None:
        from ..auth.service import AuthService

        auth_service = AuthService(auth_store, config.auth.session_expiry_hours)
        app.state.auth_store = auth_store
        app.state.auth_service = auth_service

    # Error handlers
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
        status = exc.status_code
        if status == 404:
            title, message = "Page not found", "The page you're looking for doesn't exist."
        else:
            title, message = "Something went wrong", "An unexpected error occurred."
        html = (
            "<!DOCTYPE html><html><head>"
            '<meta charset="UTF-8">'
            f"<title>{title} — Chess Trainer</title>"
            "<style>"
            "body{font-family:sans-serif;background:#161512;color:#bababa;"
            "display:flex;justify-content:center;align-items:center;min-height:100vh}"
            "div{text-align:center}"
            "h1{color:#e0e0e0;font-size:2rem;margin-bottom:0.5rem}"
            "a{color:#629924;text-decoration:none}"
            "a:hover{text-decoration:underline}"
            "</style></head><body><div>"
            f"<h1>{status}</h1><p>{message}</p>"
            '<p><a href="/">Back to dashboard</a></p>'
            "</div></body></html>"
        )
        return HTMLResponse(html, status_code=status)

    # Auth middleware runs on every request (no-op when auth disabled)
    app.add_middleware(AuthMiddleware)

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Include auth routes before main routes
    app.include_router(auth_router)
    app.include_router(router)

    return app
