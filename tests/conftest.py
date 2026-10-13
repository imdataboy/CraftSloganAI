import base64
import os

import pytest
import requests
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from slogancraftai.auth_utils import create_access_token, hash_password
from slogancraftai.db import Base
from slogancraftai.main import create_app
from slogancraftai.models import Email, LinkedInPost, User
from slogancraftai.settings import Settings


@pytest.fixture(autouse=True)
def no_external_requests(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real HTTP requests are forbidden in security tests.")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    import httplib2

    monkeypatch.setattr(httplib2.Http, "request", forbidden)
    import socket
    import urllib.request

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)


@pytest.fixture(scope="session")
def password_hash():
    return hash_password("synthetic-password")


@pytest.fixture
def context(tmp_path, password_hash):
    # Only the explicitly named disposable PostgreSQL database may be reset.
    url = os.getenv("P0_TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'test.sqlite3'}")
    if not url.startswith("sqlite:") and make_url(url).database != "p0_security_tests":
        raise RuntimeError("Refusing to reset a non-test database.")
    engine = create_engine(url)
    if url.startswith("sqlite:"):

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        url,
        "synthetic-test-signing-key-never-for-deployment-" * 2,
        base64.urlsafe_b64encode(b"0" * 32).decode(),
        ("http://127.0.0.1:5500",),
        "http://127.0.0.1:5500",
        "http://127.0.0.1:5000",
        tmp_path / "generated",
    )
    with factory.begin() as db:
        for uid in (1, 2):
            db.add(
                User(
                    full_name=f"Test {uid}",
                    email=f"user{uid}@example.invalid",
                    username=f"user{uid}",
                    password_hash=password_hash,
                )
            )
        db.flush()
        for uid in (1, 2):
            email = Email(user_id=uid, email_subject=f"Subject {uid}", email_body="Synthetic input")
            db.add(email)
            db.flush()
            db.add(
                LinkedInPost(
                    user_id=uid,
                    email_id=uid,
                    post_text=f"Synthetic post {uid}",
                    status="Pending",
                    post_status="Draft",
                )
            )
        db.add(
            LinkedInPost(
                user_id=None,
                post_text="Legacy private draft",
                status="Pending",
                post_status="Draft",
            )
        )
    app = create_app(settings, factory)
    app.config["TESTING"] = True
    yield app, factory, settings
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(context):
    return context[0].test_client()


@pytest.fixture
def auth(context):
    return {"Authorization": "Bearer " + create_access_token({"user_id": 1}, context[2])}
