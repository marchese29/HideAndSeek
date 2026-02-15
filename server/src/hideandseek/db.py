from collections.abc import AsyncGenerator, Callable
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Concatenate

from sqlmodel import Session, SQLModel, create_engine


def _find_server_root() -> Path:
    """Walk up from this file to find the directory containing pyproject.toml."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / 'pyproject.toml').exists():
            return current
        current = current.parent
    msg = 'Could not find server root (no pyproject.toml in parent directories)'
    raise RuntimeError(msg)


DB_DIR = _find_server_root() / 'data'
DB_URL = f'sqlite:///{DB_DIR / "hideandseek.db"}'

engine = create_engine(DB_URL, connect_args={'check_same_thread': False})

_session_var: ContextVar[Session] = ContextVar('_session_var')


def current_session() -> Session:
    """Return the active request-scoped session."""
    return _session_var.get()


def create_db_and_tables() -> None:
    import hideandseek.models  # noqa: F401 — registers all tables on metadata

    DB_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


async def get_session() -> AsyncGenerator[Session, None]:
    """Yield a session that commits on successful completion.

    Must be async so the ContextVar is set in the event-loop context — sync
    handler threads copy that context and see the session automatically.

    If the handler raises, the yield never resumes, commit() is never called,
    and Session.__exit__ rolls back. Every request is atomic by default.
    """
    with Session(engine) as session:
        token = _session_var.set(session)
        try:
            yield session
            session.commit()
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
