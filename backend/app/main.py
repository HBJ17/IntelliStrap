import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db, mqtt_adapter, scheduler
from .api import dashboard, device, sim, webhooks
from .config import BACKEND_DIR, get_settings
from .middleware import HardeningMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

STATIC_DIR = BACKEND_DIR / "static"
# Browsers must revalidate the dashboard files, or they keep running an old app.js after an update.
NO_CACHE = {"Cache-Control": "no-cache"}
log = logging.getLogger("app")


class DashboardFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.update(NO_CACHE)
        return response


def create_app(*, init_database: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = get_settings()
        insecure = settings.insecure_defaults()
        if insecure and not settings.is_dev:
            raise RuntimeError(f"set real values for {', '.join(insecure)} before running with APP_ENV={settings.app_env}")
        if insecure:
            log.warning("using placeholder secrets for %s (fine for local dev only)", ", ".join(insecure))
        if init_database:
            db.init_db()
        jobs = scheduler.start() if settings.scheduler_enabled else None
        if settings.mqtt_enabled:
            mqtt_adapter.start()
        yield
        if settings.mqtt_enabled:
            mqtt_adapter.stop()
        if jobs is not None:
            jobs.shutdown(wait=False)

    app = FastAPI(title="SmartBand", lifespan=lifespan)
    app.add_middleware(HardeningMiddleware)
    app.include_router(device.router)
    app.include_router(dashboard.public)
    app.include_router(dashboard.router)
    app.include_router(sim.router)
    app.include_router(webhooks.router)
    app.mount("/static", DashboardFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers=NO_CACHE)

    return app


app = create_app()
