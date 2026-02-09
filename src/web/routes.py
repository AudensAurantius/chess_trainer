"""FastAPI route handlers for the web interface."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()


def _templates(request: Request):
    """Get the Jinja2Templates instance from app state."""
    return request.app.state.templates


def _manager(request: Request):
    """Get the SessionManager from app state."""
    return request.app.state.session_manager


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the dashboard page."""
    manager = _manager(request)
    stats = manager.get_stats()
    return _templates(request).TemplateResponse(request, "dashboard.html", {"stats": stats})


@router.get("/train", response_class=HTMLResponse)
async def train_page(request: Request):
    """Render the training page."""
    return _templates(request).TemplateResponse(request, "train.html")


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    """Render the detailed statistics page."""
    manager = _manager(request)
    stats = manager.get_stats()
    return _templates(request).TemplateResponse(request, "stats.html", {"stats": stats})


# --- API endpoints ---


@router.post("/api/session/start")
async def api_session_start(request: Request):
    """Start a new training session."""
    manager = _manager(request)
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    max_new = body.get("max_new")
    max_reviews = body.get("max_reviews")
    count = manager.start_session(max_new=max_new, max_reviews=max_reviews)
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
    return JSONResponse(
        {
            "status": "ok",
            "fen": state.fen,
            "side_to_move": state.side_to_move,
            "challenge": state.challenge,
            "remaining": manager.remaining,
            "exercise_num": manager.stats.exercises_shown if manager.stats else 1,
            "tags": state.exercise.tags[:3],
            "difficulty": state.exercise.difficulty,
        }
    )


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


@router.get("/api/analytics/retention")
async def api_analytics_retention(request: Request):
    """Get retention curve data."""
    manager = _manager(request)
    result = manager.get_retention_curve()
    return JSONResponse(result)
