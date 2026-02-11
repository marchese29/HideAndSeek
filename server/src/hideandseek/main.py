from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title='HideAndSeek',
    description='Geographic Hide and Seek game server',
    version='0.1.0',
)


@app.get('/')
async def root() -> dict[str, str]:
    return {'message': 'Hello, HideAndSeek!'}


@app.get('/health')
async def health() -> dict[str, str]:
    return {'status': 'ok'}
