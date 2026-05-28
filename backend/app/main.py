from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.routers import api_router

app = FastAPI(title=settings.app_name)

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
