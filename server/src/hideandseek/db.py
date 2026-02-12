from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

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
    with Session(engine) as session:
        yield session
