"""FastAPI route handlers for the web interface."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

router = APIRouter()

STATIC_DIR = Path(__file__).parent / "static"


def _templates(request: Request):
    """Get the Jinja2Templates instance from app state."""
    return request.app.state.templates


def _manager(request: Request):
    """Get the per-user SessionManager from the pool."""
    user = _user(request)
    pool = request.app.state.manager_pool
    return pool.get(user.id if user else None)


def _user(request: Request):
    """Get the authenticated user (or None) from middleware state."""
    return getattr(request.state, "user", None)


@router.get("/sw.js")
async def service_worker():
    """Serve the service worker from root scope."""
    return FileResponse(
        STATIC_DIR / "js" / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@router.get("/manifest.json")
async def manifest():
    """Serve the PWA manifest from root."""
    return FileResponse(
        STATIC_DIR / "manifest.json",
        media_type="application/manifest+json",
    )


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the dashboard page."""
    manager = _manager(request)
    stats = manager.get_stats()
    return _templates(request).TemplateResponse(
        request, "dashboard.html", {"stats": stats, "user": _user(request)}
    )


@router.get("/train", response_class=HTMLResponse)
async def train_page(request: Request):
    """Render the training page."""
    return _templates(request).TemplateResponse(request, "train.html", {"user": _user(request)})


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    """Render the detailed statistics page."""
    manager = _manager(request)
    stats = manager.get_stats()
    return _templates(request).TemplateResponse(
        request, "stats.html", {"stats": stats, "user": _user(request)}
    )


@router.get("/import", response_class=HTMLResponse)
async def import_page(request: Request):
    """Render the import page."""
    manager = _manager(request)
    return _templates(request).TemplateResponse(
        request,
        "import.html",
        {
            "user": _user(request),
            "has_lichess_token": manager.has_lichess_token(),
        },
    )


# --- API endpoints ---


@router.post("/api/import/lichess")
async def api_import_lichess(request: Request):
    """Import puzzles from Lichess."""
    manager = _manager(request)
    body = await request.json()
    count = min(int(body.get("count", 20)), 100)
    difficulty = body.get("difficulty") or None
    themes = body.get("themes") or None

    try:
        result = manager.import_lichess_puzzles(count=count, difficulty=difficulty, themes=themes)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    return JSONResponse(result)


@router.post("/api/import/lichess-failed")
async def api_import_lichess_failed(request: Request):
    """Import previously failed Lichess puzzles."""
    manager = _manager(request)
    body = await request.json()
    count = min(int(body.get("count", 50)), 100)
    since = body.get("since") or None
    auto_tag = body.get("auto_tag", True)

    try:
        result = manager.import_lichess_failed_puzzles(count=count, since=since, auto_tag=auto_tag)
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "unauthorized" in error_msg.lower():
            return JSONResponse(
                {"error": "Lichess token is missing or invalid. Set LICHESS_TOKEN."},
                status_code=401,
            )
        return JSONResponse({"error": error_msg}, status_code=500)

    return JSONResponse(result)


@router.post("/api/import/lichess-games")
async def api_import_lichess_games(request: Request):
    """Import exercises from Lichess game analysis (server evals)."""
    manager = _manager(request)
    body = await request.json()

    username = body.get("username", "").strip()
    if not username:
        return JSONResponse({"error": "Username is required"}, status_code=400)

    max_games = min(int(body.get("max_games", 10)), 50)
    color = body.get("color") or None
    perf_type = body.get("perf_type") or None
    rated = body.get("rated")

    try:
        result = manager.import_lichess_games(
            username=username,
            max_games=max_games,
            color=color,
            perf_type=perf_type,
            rated=rated,
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    return JSONResponse(result)


@router.post("/api/import/chesscom")
async def api_import_chesscom(request: Request):
    """Import puzzles from Chess.com."""
    manager = _manager(request)
    body = await request.json()
    count = min(int(body.get("count", 20)), 100)
    include_daily = body.get("include_daily", True)

    try:
        result = manager.import_chesscom_puzzles(count=count, include_daily=include_daily)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    return JSONResponse(result)


@router.post("/api/import/lichess-study")
async def api_import_lichess_study(request: Request):
    """Import opening lines from a Lichess study."""
    manager = _manager(request)
    body = await request.json()

    study_url = body.get("study_url", "").strip()
    if not study_url:
        return JSONResponse({"error": "Study URL or ID is required"}, status_code=400)

    color = body.get("color", "").strip()
    if color not in ("white", "black"):
        return JSONResponse({"error": "Color must be 'white' or 'black'"}, status_code=400)

    try:
        result = manager.import_lichess_study(study_url=study_url, color=color)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            return JSONResponse({"error": error_msg}, status_code=404)
        return JSONResponse({"error": error_msg}, status_code=500)

    return JSONResponse(result)


@router.post("/api/session/start")
async def api_session_start(request: Request):
    """Start a new training session."""
    manager = _manager(request)
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    max_new = body.get("max_new")
    max_reviews = body.get("max_reviews")
    include_tags = body.get("include_tags") or None
    adapt_difficulty = body.get("adapt_difficulty")
    hide_type = body.get("hide_type", False)
    exercise_types = body.get("exercise_types") or None
    max_duration = body.get("max_duration_minutes")
    count = manager.start_session(
        max_new=max_new,
        max_reviews=max_reviews,
        include_tags=include_tags,
        adapt_difficulty=adapt_difficulty,
        hide_exercise_type=bool(hide_type),
        exercise_types=exercise_types,
        max_duration_minutes=int(max_duration) if max_duration else None,
    )
    return JSONResponse({"status": "started", "queue_size": count})


@router.get("/api/session/next")
async def api_session_next(request: Request):
    """Get the next exercise."""
    manager = _manager(request)
    state = manager.next_exercise()
    if state is None:
        # Session complete — return stats
        stats = manager.stats
        return JSONResponse(
            {
                "status": "complete",
                "stats": {
                    "exercises_shown": stats.exercises_shown if stats else 0,
                    "correct": stats.correct if stats else 0,
                    "incorrect": stats.incorrect if stats else 0,
                    "partial": stats.partial if stats else 0,
                    "accuracy": stats.accuracy if stats else 0,
                },
            }
        )
    response = {
        "status": "ok",
        "fen": state.fen,
        "side_to_move": state.side_to_move,
        "challenge": state.challenge,
        "remaining": manager.remaining,
        "exercise_num": manager.stats.exercises_shown if manager.stats else 1,
        "tags": state.exercise.tags[:3],
        "difficulty": state.exercise.difficulty,
    }

    # Include exercise type unless hidden
    if not manager.hide_exercise_type:
        response["exercise_type"] = state.exercise.exercise_type.name

    # Include time info for duration-limited sessions
    if manager.remaining_minutes is not None:
        response["elapsed_minutes"] = round(manager.elapsed_minutes or 0, 1)
        response["remaining_minutes"] = round(manager.remaining_minutes, 1)

    # Include game context for own-game exercises (if enabled in config)
    config = request.app.state.config
    if config.own_game_eval.show_game_context:
        game_context = state.exercise.metadata.get("game_context")
        if game_context:
            response["game_context"] = game_context

    # Signal whether "show my move" hint is available
    if state.exercise.metadata.get("played_move_uci"):
        response["has_played_move"] = True

    return JSONResponse(response)


@router.post("/api/session/move")
async def api_session_move(request: Request):
    """Submit a move for the current exercise."""
    manager = _manager(request)
    body = await request.json()
    move_uci = body.get("move")
    if not move_uci:
        return JSONResponse({"valid": False, "feedback": "No move provided"}, status_code=400)
    result = manager.submit_move(move_uci)
    return JSONResponse(result)


@router.post("/api/session/rate")
async def api_session_rate(request: Request):
    """Submit a rating for the current exercise."""
    manager = _manager(request)
    body = await request.json()
    rating = body.get("rating")
    if rating not in (1, 2, 3, 4):
        return JSONResponse({"error": "Rating must be 1-4"}, status_code=400)
    result = manager.rate(rating)
    return JSONResponse(result)


@router.get("/api/session/solution")
async def api_session_solution(request: Request):
    """Get the solution for the current exercise."""
    manager = _manager(request)
    info = manager.get_solution_info()
    if info is None:
        return JSONResponse({"error": "No active exercise"}, status_code=400)
    return JSONResponse(info)


@router.get("/api/session/my-move")
async def api_session_my_move(request: Request):
    """Get the user's original played move for own-game exercises.

    Returns the move that the user actually played in the game, allowing
    them to see what to avoid. Applies a mild scoring penalty (0.85x).
    """
    manager = _manager(request)
    info = manager.get_played_move()
    if info is None:
        return JSONResponse({"error": "No played move available"}, status_code=404)
    return JSONResponse(info)


@router.post("/api/session/end")
async def api_session_end(request: Request):
    """End the current session."""
    manager = _manager(request)
    stats = manager.end_session()
    if stats is None:
        return JSONResponse({"status": "no_session"})
    return JSONResponse(
        {
            "status": "ended",
            "stats": {
                "exercises_shown": stats.exercises_shown,
                "correct": stats.correct,
                "incorrect": stats.incorrect,
                "partial": stats.partial,
                "accuracy": stats.accuracy,
                "duration_minutes": round(stats.duration_minutes, 1),
            },
        }
    )


@router.get("/api/stats")
async def api_stats(request: Request):
    """Get overall statistics."""
    manager = _manager(request)
    return JSONResponse(manager.get_stats())


# --- Analytics endpoints ---


@router.get("/api/analytics/accuracy")
async def api_analytics_accuracy(request: Request):
    """Get accuracy trend data."""
    manager = _manager(request)
    days = int(request.query_params.get("days", "30"))
    granularity = request.query_params.get("granularity", "day")
    exercise_type = request.query_params.get("exercise_type") or None

    result = manager.get_accuracy_trend(
        days=days, granularity=granularity, exercise_type=exercise_type
    )
    return JSONResponse(result)


@router.get("/api/analytics/weak-areas")
async def api_analytics_weak_areas(request: Request):
    """Get weak areas data."""
    manager = _manager(request)
    min_reviews = int(request.query_params.get("min_reviews", "5"))
    limit = int(request.query_params.get("limit", "20"))

    result = manager.get_weak_areas(min_reviews=min_reviews, limit=limit)
    return JSONResponse(result)


@router.get("/api/analytics/streaks")
async def api_analytics_streaks(request: Request):
    """Get streak data."""
    manager = _manager(request)
    lookback_days = int(request.query_params.get("lookback_days", "90"))

    result = manager.get_streaks(lookback_days=lookback_days)
    return JSONResponse(result)


# --- Bundle endpoints ---


@router.get("/bundles", response_class=HTMLResponse)
async def bundles_page(request: Request):
    """Render the bundles management page."""
    manager = _manager(request)
    bundles = manager.list_bundles()
    return _templates(request).TemplateResponse(
        request, "bundles.html", {"bundles": bundles, "user": _user(request)}
    )


@router.get("/api/bundles")
async def api_bundles_list(request: Request):
    """List all bundles."""
    manager = _manager(request)
    return JSONResponse({"bundles": manager.list_bundles()})


@router.post("/api/bundles")
async def api_bundles_create(request: Request):
    """Create a new bundle."""
    from ..exercises.bundle import (
        BundleConfig,
        ExerciseBundle,
        WoodpeckerCycle,
        generate_bundle_id,
        validate_slug,
    )

    body = await request.json()
    slug = body.get("slug", "")
    try:
        validated = validate_slug(slug)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    woodpecker = body.get("woodpecker", False)
    woodpecker_cycles = []
    if woodpecker:
        woodpecker_cycles = [
            WoodpeckerCycle(cycle_number=1, rest_days=0, time_limit_seconds=None),
            WoodpeckerCycle(cycle_number=2, rest_days=1, time_limit_seconds=None),
            WoodpeckerCycle(cycle_number=3, rest_days=3, time_limit_seconds=60),
            WoodpeckerCycle(cycle_number=4, rest_days=7, time_limit_seconds=30),
        ]

    bundle = ExerciseBundle(
        id=generate_bundle_id(validated),
        name=body.get("name") or validated.replace("-", " ").title(),
        description=body.get("description", ""),
        config=BundleConfig(
            woodpecker_mode=woodpecker,
            woodpecker_cycles=woodpecker_cycles,
            pass_threshold=body.get("threshold", 0.9),
            shuffle=body.get("shuffle", False),
        ),
    )

    manager = _manager(request)
    repo = manager._open_repo()
    try:
        repo.bundles.create(bundle)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)

    return JSONResponse({"status": "created", "id": bundle.id})


@router.get("/api/bundles/{slug}")
async def api_bundles_detail(request: Request, slug: str):
    """Get bundle detail with progress."""
    from ..exercises.bundle import generate_bundle_id, validate_slug

    try:
        validated = validate_slug(slug)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    manager = _manager(request)
    repo = manager._open_repo()
    bundle = repo.bundles.get(generate_bundle_id(validated))
    if not bundle:
        return JSONResponse({"error": "Bundle not found"}, status_code=404)

    progress = repo.bundles.get_progress(bundle.id)
    return JSONResponse(
        {
            "id": bundle.id,
            "name": bundle.name,
            "description": bundle.description,
            "exercise_count": bundle.exercise_count,
            "exercise_ids": bundle.exercise_ids[:50],
            "config": bundle.config.to_dict(),
            "progress": progress.to_dict() if progress else None,
        }
    )


@router.delete("/api/bundles/{slug}")
async def api_bundles_delete(request: Request, slug: str):
    """Delete a bundle."""
    from ..exercises.bundle import generate_bundle_id, validate_slug

    try:
        validated = validate_slug(slug)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    manager = _manager(request)
    repo = manager._open_repo()
    deleted = repo.bundles.delete(generate_bundle_id(validated))
    if not deleted:
        return JSONResponse({"error": "Bundle not found"}, status_code=404)
    return JSONResponse({"status": "deleted"})


@router.post("/api/bundles/{slug}/train")
async def api_bundles_train(request: Request, slug: str):
    """Start a bundle training session."""
    manager = _manager(request)
    result = manager.start_bundle_session(slug)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@router.get("/api/bundles/{slug}/progress")
async def api_bundles_progress(request: Request, slug: str):
    """Get cycle history for a bundle."""
    from ..exercises.bundle import generate_bundle_id, validate_slug

    try:
        validated = validate_slug(slug)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    manager = _manager(request)
    repo = manager._open_repo()
    progress = repo.bundles.get_progress(generate_bundle_id(validated))
    if not progress:
        return JSONResponse({"cycles": [], "current_cycle": 1})
    return JSONResponse(
        {
            "current_cycle": progress.current_cycle,
            "cycles": [c.to_dict() for c in progress.completed_cycles],
        }
    )


@router.get("/api/analytics/retention")
async def api_analytics_retention(request: Request):
    """Get retention curve data."""
    manager = _manager(request)
    result = manager.get_retention_curve()
    return JSONResponse(result)
