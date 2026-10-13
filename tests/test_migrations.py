from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from slogancraftai.db import Base
from slogancraftai.initialize_db import initialize


def configuration_env(monkeypatch, settings):
    monkeypatch.setattr("slogancraftai.settings.load_dotenv", lambda **kwargs: None)
    for key, value in {
        "DATABASE_URL": settings.database_url,
        "JWT_SECRET_KEY": settings.jwt_secret,
        "TOKEN_ENCRYPTION_KEY": settings.token_encryption_key,
        "FRONTEND_ORIGINS": settings.frontend_origins[0],
        "FRONTEND_URL": settings.frontend_url,
        "BACKEND_URL": settings.backend_url,
    }.items():
        monkeypatch.setenv(key, value)


def alembic_config():
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    return config


def test_additive_migration_preserves_and_quarantines_legacy(context, monkeypatch):
    factory, settings = context[1:]
    configuration_env(monkeypatch, settings)
    engine = factory.kw["bind"]
    Base.metadata.drop_all(engine)
    legacy = sa.MetaData()
    users = sa.Table(
        "users",
        legacy,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String),
    )
    for name in ("emails", "slogans", "images", "linkedin_posts"):
        sa.Table(
            name,
            legacy,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("legacy_content", sa.String),
        )
    legacy.create_all(engine)
    with engine.begin() as db:
        db.execute(users.insert().values(id=1, email="legacy@example.invalid"))
        for name in ("emails", "slogans", "images", "linkedin_posts"):
            db.execute(legacy.tables[name].insert().values(id=1, legacy_content="preserve-me"))
    # Existing installation has applied the original revision; this test exercises
    # only the additive P0 migration, not the pre-existing incomplete bootstrap.
    config = alembic_config()
    command.stamp(config, "3d33747b84ae")
    command.upgrade(config, "head")
    with engine.connect() as db:
        for name in ("emails", "slogans", "images", "linkedin_posts"):
            row = db.execute(sa.text(f"SELECT legacy_content, user_id FROM {name}")).one()
            assert row.legacy_content == "preserve-me"
            assert row.user_id is None
        assert not db.execute(sa.text("SELECT is_generated FROM images")).scalar()
        assert (
            db.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
            == "p0_security_20261013"
        )
    inspector = sa.inspect(engine)
    for name in ("emails", "slogans", "images", "linkedin_posts"):
        assert any(fk["referred_table"] == "users" for fk in inspector.get_foreign_keys(name))
    assert {"oauth_states", "oauth_credentials"} <= set(inspector.get_table_names())
    command.upgrade(config, "head")  # Applying head again changes nothing.
    # Fixture cleanup expects current metadata. Drop this isolated legacy test schema.
    reflected = sa.MetaData()
    reflected.reflect(engine)
    reflected.drop_all(engine)


def test_empty_initialization_and_refusal_to_overwrite(context, monkeypatch):
    factory, settings = context[1:]
    engine = factory.kw["bind"]
    Base.metadata.drop_all(engine)
    configuration_env(monkeypatch, settings)
    initialize()
    assert set(Base.metadata.tables) <= set(sa.inspect(engine).get_table_names())
    with pytest.raises(RuntimeError, match="not empty"):
        initialize()
    with engine.begin() as db:
        db.execute(sa.text("DROP TABLE alembic_version"))
