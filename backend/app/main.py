import logging
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.routers import api_router

app = FastAPI(title=settings.app_name)

# The backend runs as a scheduled task with nowhere for stderr to go, so an
# unhandled error reached the client as a bare "internal server error" and the
# traceback was lost. Everything needed to diagnose one now lands in a file.
_LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_handler = RotatingFileHandler(_LOG_DIR / "backend.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
_log = logging.getLogger("spdxlims.backend")
_log.setLevel(logging.INFO)
_log.addHandler(_handler)


@app.exception_handler(Exception)
async def log_unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Log the traceback and hand the client a reference to quote.

    The reference is the point: it ties what someone saw on screen to the exact
    entry in the log, instead of leaving us to guess which save failed.
    """
    reference = uuid.uuid4().hex[:8]
    _log.exception(
        "unhandled error %s on %s %s", reference, request.method, request.url.path
    )
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error (reference {reference})"},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/admin", include_in_schema=False)
def admin_page() -> FileResponse:
    return FileResponse(static_dir / "admin" / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}
