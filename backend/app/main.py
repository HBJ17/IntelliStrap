import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db, scheduler
from .api import dashboard, device, sim
from .config import BACKEND_DIR, get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

STATIC_DIR = BACKEND_DIR / "static"


def create_app(*, init_database: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if init_database:
            db.init_db()
        jobs = scheduler.start() if get_settings().scheduler_enabled else None
        yield
        if jobs is not None:
            jobs.shutdown(wait=False)

    app = FastAPI(title="SmartBand", lifespan=lifespan)
    app.include_router(device.router)
    app.include_router(dashboard.public)
    app.include_router(dashboard.router)
    app.include_router(sim.router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
