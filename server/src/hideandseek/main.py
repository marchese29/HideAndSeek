from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from hideandseek.db import create_db_and_tables


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    create_db_and_tables()
    yield


app = FastAPI(
    title='HideAndSeek',
    description='Geographic Hide and Seek game server',
    version='0.1.0',
    lifespan=lifespan,
)


@app.get('/')
async def root() -> dict[str, str]:
    return {'message': 'Hello, HideAndSeek!'}


@app.get('/health')
async def health() -> dict[str, str]:
    return {'status': 'ok'}
