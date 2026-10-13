"""Initialize only an EMPTY database; existing databases must use Alembic."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from . import models  # noqa: F401 - register tables before create_all in a fresh process
from .db import Base, create_session_factory
from .settings import Settings


def initialize():
    _, engine = create_session_factory(Settings.from_env().database_url)
    if inspect(engine).get_table_names():
        raise RuntimeError("Database is not empty. Back it up and use alembic upgrade head.")
    Base.metadata.create_all(engine)
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    command.stamp(cfg, "head")
    engine.dispose()
    print("Empty database initialized at the current schema version.")


if __name__ == "__main__":
    initialize()
