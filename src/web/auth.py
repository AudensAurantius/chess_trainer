"""Auth routes and middleware for the web UI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from ..auth.service import AuthService

auth_router = APIRouter()

# Paths that don't require authentication
_EXEMPT_PREFIXES = ("/login", "/register", "/static", "/favicon.ico", "/sw.js", "/manifest.json")


# ── Middleware ────────────────────────────────────────────────────────────────


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforce authentication on all routes except login/register/static."""

    async def dispatch(self, request: Request, call_next):
        """Check session cookie and enforce auth on non-exempt paths."""
        auth_service: AuthService | None = getattr(request.app.state, "auth_service", None)

        # Auth disabled — pass through with no user
        if auth_service is None:
            request.state.user = None
            return await call_next(request)

        path = request.url.path

        # Exempt paths
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            request.state.user = None
            return await call_next(request)

        # Check session cookie
        token = request.cookies.get("session_token")
        user = auth_service.validate_session(token) if token else None

        if user is not None:
            request.state.user = user
            return await call_next(request)

        # Unauthenticated
        if path.startswith("/api/"):
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        return RedirectResponse("/login", status_code=302)


# ── Routes ────────────────────────────────────────────────────────────────────


def _auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def _templates(request: Request):
    return request.app.state.templates


@auth_router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render the login form."""
    return _templates(request).TemplateResponse(
        request, "login.html", {"error": None, "show_nav": False}
    )


@auth_router.post("/login")
async def login_submit(request: Request):
    """Validate credentials and set session cookie."""
    from ..auth.service import InactiveAccountError, InvalidCredentialsError

    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")

    svc = _auth_service(request)
    try:
        session = svc.login(username, password)
    except (InvalidCredentialsError, InactiveAccountError) as e:
        return _templates(request).TemplateResponse(
            request, "login.html", {"error": str(e), "show_nav": False}, status_code=400
        )

    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        "session_token",
        session.token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=svc.session_expiry_hours * 3600,
    )
    return response


@auth_router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Render the registration form."""
    return _templates(request).TemplateResponse(
        request, "register.html", {"error": None, "show_nav": False}
    )


@auth_router.post("/register")
async def register_submit(request: Request):
    """Validate invite + credentials, create user, auto-login."""
    from ..auth.service import AuthError

    form = await request.form()
    invite_code = form.get("invite_code", "")
    username = form.get("username", "")
    password = form.get("password", "")
    confirm = form.get("confirm_password", "")

    if password != confirm:
        return _templates(request).TemplateResponse(
            request,
            "register.html",
            {"error": "Passwords do not match", "show_nav": False},
            status_code=400,
        )

    svc = _auth_service(request)
    try:
        user = svc.register(username, password, invite_code)
    except AuthError as e:
        return _templates(request).TemplateResponse(
            request, "register.html", {"error": str(e), "show_nav": False}, status_code=400
        )

    # Auto-login after registration
    session = svc.login(user.username, password)
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        "session_token",
        session.token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=svc.session_expiry_hours * 3600,
    )
    return response


@auth_router.post("/logout")
async def logout(request: Request):
    """Delete session and clear cookie."""
    token = request.cookies.get("session_token")
    if token:
        svc = _auth_service(request)
        svc.logout(token)
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("session_token")
    return response
