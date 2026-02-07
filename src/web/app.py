"""FastAPI application factory."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__
from ..config import AppConfig
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
    app = FastAPI(title="Chess Trainer", version=__version__)

    # Store config and session manager in app state
    app.state.config = config
    app.state.session_manager = SessionManager(config)
    app.state.templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Include routes
    app.include_router(router)

    return app
