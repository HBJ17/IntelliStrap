import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import db
from .api import dashboard, device

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(*, init_database: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if init_database:
            db.init_db()
        yield

    app = FastAPI(title="SmartBand", lifespan=lifespan)
    app.include_router(device.router)
    app.include_router(dashboard.public)
    app.include_router(dashboard.router)
    return app


app = create_app()
