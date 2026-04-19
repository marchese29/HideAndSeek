from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from hideandseek.logging import setup_logging
from hideandseek.middleware import AccessLogMiddleware
from hideandseek.routers import endgame, events, games, location, maps, questions
from hideandseek_core.db import create_db_and_tables


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging()
    create_db_and_tables()
    yield


app = FastAPI(
    title='HideAndSeek',
    description='Geographic Hide and Seek game server',
    version='0.1.0',
    lifespan=lifespan,
)

app.add_middleware(AccessLogMiddleware)

app.include_router(maps.router)
app.include_router(games.router)
app.include_router(events.router)
app.include_router(location.router)
app.include_router(questions.router)
app.include_router(endgame.router)


@app.get('/')
async def root() -> dict[str, str]:
    return {'message': 'Hello, HideAndSeek!'}


@app.get('/healthz', status_code=200, response_class=Response)
async def healthz() -> Response:
    return Response(status_code=200)
