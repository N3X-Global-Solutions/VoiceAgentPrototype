"""Voice Agent Studio API: FastAPI app wiring. Routes live in app/api/, one module per area."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import ValidationError

from app.api import auth, calls, clients, live, meta, testing, usage
from app.core import config
from app.core.db import init_db
from app.core.security import AuthMiddleware

FRONTEND_DIST = config.BACKEND_DIR.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from app.providers import catalog

    ready = [info["name"] for p, info in catalog.providers().items() if catalog.configured(p)]
    if ready:
        logger.info(f"Voice AI providers with keys: {', '.join(ready)}")
    else:
        logger.warning("No voice AI provider key is set (SARVAM_API_KEY / NAVANA_API_KEY / GNANI_API_KEY): calls will fail")
    yield
    await live.webrtc_handler.close()


app = FastAPI(title="Voice Agent Studio", lifespan=lifespan)
app.add_middleware(AuthMiddleware)  # every /api route needs a session unless listed as public
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (auth, meta, clients, testing, live, calls, usage):
    app.include_router(module.router)


@app.exception_handler(ValidationError)
async def validation_error(_: Request, exc: ValidationError):
    return Response(status_code=422, content=exc.json(), media_type="application/json")


# ---------------------------------------------------------------- frontend (production build)

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        file = FRONTEND_DIST / path
        if path and file.is_file() and Path(file).resolve().is_relative_to(FRONTEND_DIST.resolve()):
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")
