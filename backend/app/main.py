import asyncio
import time
from contextlib import asynccontextmanager, suppress
from collections import defaultdict, deque
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import text
from app.config import settings
from app.database import async_session_maker
from app.routers import adaptive_thresholds, analytics, attachments, auth, counterfactual, datasets, enterprise, evaluation, experiments, graph, health, platform, playbooks, prevention, queues, red_team, release_b, resolution_passport, safe_actions, tickets, v2_governance, workflow

async def cleanup_sessions() -> None:
    while True:
        try:
            async with async_session_maker() as db:
                await db.execute(text("DELETE FROM auth_sessions WHERE expires_at < now() - interval '7 days'")); await db.commit()
        except Exception:
            pass
        await asyncio.sleep(settings.session_cleanup_interval_seconds)

@asynccontextmanager
async def lifespan(_: FastAPI):
    task=asyncio.create_task(cleanup_sessions())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError): await task

app = FastAPI(title="TicketSense API", version="0.1.0", lifespan=lifespan)

_request_windows: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def enterprise_security(request: Request, call_next):
    now = time.monotonic(); client = request.client.host if request.client else "unknown"
    window = _request_windows[client]
    while window and now - window[0] > settings.general_rate_limit_window_seconds: window.popleft()
    if len(window) >= settings.general_rate_limit_requests:
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
    window.append(now)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(tickets.router)
app.include_router(attachments.router)
app.include_router(analytics.router)
app.include_router(platform.router)
app.include_router(queues.router)
app.include_router(workflow.router)
app.include_router(release_b.router)
app.include_router(enterprise.router)
app.include_router(playbooks.router)
app.include_router(safe_actions.router)
app.include_router(prevention.router)
app.include_router(v2_governance.router)
app.include_router(datasets.router)
app.include_router(evaluation.router)
app.include_router(adaptive_thresholds.router)
app.include_router(resolution_passport.router)
app.include_router(counterfactual.router)
app.include_router(graph.router)
app.include_router(experiments.router)
app.include_router(red_team.router)
