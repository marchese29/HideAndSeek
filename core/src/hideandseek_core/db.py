import os
from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cache

import sqlalchemy as sa
import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL', '')


@cache
def get_engine() -> sa.Engine:
    """Return the shared engine, creating it on first call.

    Requires DATABASE_URL to be set. Cached so all callers share one engine.
    `pool_pre_ping=True` issues a lightweight validation before each connection
    checkout so pooled connections survive Aurora Serverless v2 auto-pause.
    """
    if not DATABASE_URL:
        msg = 'DATABASE_URL environment variable is required'
        raise RuntimeError(msg)
    return create_engine(DATABASE_URL, pool_pre_ping=True)


_session_var: ContextVar[Session] = ContextVar('_session_var')


def get_session() -> Session:
    """Return the active request-scoped session."""
    return _session_var.get()


def register[T](*objects: T) -> T:
    """Add new ORM objects to the session, flush, and return the last object.

    Enables inline usage: ``question = register(Question(...))``
    """
    session = get_session()
    for obj in objects:
        session.add(obj)
    session.flush()
    return objects[-1]


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Sync session with ContextVar — for background tasks and scripts.

    Sets the ContextVar so query functions using get_session() work naturally.
    Commits on success, rolls back on exception (via Session.__exit__).
    """
    with Session(get_engine()) as session:
        token = _session_var.set(session)
        try:
            yield session
            session.commit()
        finally:
            _session_var.reset(token)


async def session_dependency() -> AsyncGenerator[Session, None]:
    """Yield a session that commits on successful completion.

    Must be async so the ContextVar is set in the event-loop context — sync
    handler threads copy that context and see the session automatically.

    If the handler raises, the yield never resumes, commit() is never called,
    and Session.__exit__ rolls back. Every request is atomic by default.
    """
    with Session(get_engine()) as session:
        token = _session_var.set(session)
        logger.debug('session_opened')
        try:
            yield session
            session.commit()
            logger.debug('session_committed')
        finally:
            _session_var.reset(token)
