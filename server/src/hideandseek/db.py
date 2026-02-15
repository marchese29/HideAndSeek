from collections.abc import Callable, Generator
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


def create_db_and_tables() -> None:
    import hideandseek.models  # noqa: F401 — registers all tables on metadata

    DB_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """Yield a session that commits on successful completion.

    If the handler raises, the yield never resumes, commit() is never called,
    and Session.__exit__ rolls back. Every request is atomic by default.
    """
    with Session(engine) as session:
        yield session
        session.commit()


def persisted[T, **P](
    fn: Callable[Concatenate[Session, P], T],
) -> Callable[Concatenate[Session, P], T]:
    """Flush the session after the function runs.

    Decorated functions should session.add() their objects and return them.
    The decorator flushes to materialize the writes within the transaction
    (making them visible to subsequent queries in the same request).
    The boundary commit in get_session() finalizes everything.
    """

    @wraps(fn)
    def wrapper(session: Session, /, *args: P.args, **kwargs: P.kwargs) -> T:
        result = fn(session, *args, **kwargs)
        session.flush()
        return result

    return wrapper
