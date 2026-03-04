import os
import time
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Concatenate

import sqlalchemy as sa
import structlog
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from hideandseek.utils import find_server_root

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_default_db_url = f'sqlite:///{find_server_root() / "data" / "hideandseek.db"}'
DATABASE_URL = os.environ.get('DATABASE_URL', _default_db_url)

_connect_args: dict[str, bool] = {}
if DATABASE_URL.startswith('sqlite'):
    _connect_args['check_same_thread'] = False

engine = create_engine(DATABASE_URL, connect_args=_connect_args)

if DATABASE_URL.startswith('sqlite'):
    from pathlib import Path

    from geoalchemy2 import load_spatialite

    if 'SPATIALITE_LIBRARY_PATH' not in os.environ:
        _candidates = [
            Path('/opt/homebrew/lib/mod_spatialite.dylib'),  # macOS ARM
            Path('/usr/local/lib/mod_spatialite.dylib'),  # macOS Intel
            Path('/usr/lib/x86_64-linux-gnu/mod_spatialite.so'),  # Debian/Ubuntu
        ]
        for p in _candidates:
            if p.exists():
                os.environ['SPATIALITE_LIBRARY_PATH'] = str(p)
                break

    event.listen(engine, 'connect', load_spatialite)

_session_var: ContextVar[Session] = ContextVar('_session_var')


def current_session() -> Session:
    """Return the active request-scoped session."""
    return _session_var.get()


def create_db_and_tables(*, max_retries: int = 10) -> None:
    import hideandseek.models  # noqa: F401 — registers all tables on metadata

    if DATABASE_URL.startswith('sqlite'):
        _db_dir = find_server_root() / 'data'
        _db_dir.mkdir(parents=True, exist_ok=True)
    elif DATABASE_URL.startswith('postgresql'):
        for attempt in range(max_retries):
            try:
                with engine.connect() as conn:
                    conn.execute(sa.text('CREATE EXTENSION IF NOT EXISTS postgis'))
                    conn.commit()
                break
            except OperationalError:
                if attempt == max_retries - 1:
                    raise
                logger.warning('db_connect_retry', attempt=attempt + 1, max_retries=max_retries)
                time.sleep(1)
    from hideandseek.models.base import Base

    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Sync session with ContextVar — for background tasks and scripts.

    Sets the ContextVar so @db_read/@db_write query functions work naturally.
    Commits on success, rolls back on exception (via Session.__exit__).
    """
    with Session(engine) as session:
        token = _session_var.set(session)
        try:
            yield session
            session.commit()
        finally:
            _session_var.reset(token)


async def get_session() -> AsyncGenerator[Session, None]:
    """Yield a session that commits on successful completion.

    Must be async so the ContextVar is set in the event-loop context — sync
    handler threads copy that context and see the session automatically.

    If the handler raises, the yield never resumes, commit() is never called,
    and Session.__exit__ rolls back. Every request is atomic by default.
    """
    with Session(engine) as session:
        token = _session_var.set(session)
        logger.debug('session_opened')
        try:
            yield session
            session.commit()
            logger.debug('session_committed')
        finally:
            _session_var.reset(token)


def db_read[T, **P](
    fn: Callable[Concatenate[Session, P], T],
) -> Callable[P, T]:
    """Inject the current session as the first argument."""

    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        return fn(current_session(), *args, **kwargs)

    return wrapper


def db_write[T, **P](
    fn: Callable[Concatenate[Session, P], T],
) -> Callable[P, T]:
    """Inject session and flush after the function runs.

    Decorated functions should session.add() their objects and return them.
    The decorator flushes to materialize the writes within the transaction
    (making them visible to subsequent queries in the same request).
    The boundary commit in get_session() finalizes everything.
    """

    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        session = current_session()
        result = fn(session, *args, **kwargs)
        session.flush()
        return result

    return wrapper
