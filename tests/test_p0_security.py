import hashlib
import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
import requests
from PIL import Image as PILImage
from sqlalchemy import update

from slogancraftai.main import publish_scheduled_posts
from slogancraftai.models import Image, LinkedInPost, OAuthCredential, OAuthState
from slogancraftai.publishing import PostConflict, publish_post
from slogancraftai.security import (
    SecurityError,
    consume_state,
    issue_state,
    state_cookie,
)
from slogancraftai.settings import ConfigurationError, Settings
from slogancraftai.tools.linkedin_poster import LinkedInError, LinkedInPoster

PROTECTED = [
    ("POST", "/run_agents"),
    ("POST", "/run_agents_manual"),
    ("GET", "/validate_post"),
    ("POST", "/validate_post"),
    ("POST", "/schedule_post"),
    ("POST", "/post/linkedin"),
    ("DELETE", "/delete_scheduled_post"),
    ("GET", "/upcoming_events"),
    ("GET", "/images/1"),
    ("GET", "/auth/gmail"),
    ("GET", "/auth/linkedin"),
    ("GET", "/auth/gmail/status"),
    ("GET", "/auth/linkedin/status"),
    ("POST", "/chat"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
@pytest.mark.parametrize("token", [None, "invalid-token"])
def test_jwt_required(client, method, path, token):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = client.open(path, method=method, headers=headers, json={})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "change", ["expired", "issuer", "audience", "algorithm", "missing_exp", "unknown_user"]
)
def test_invalid_jwt_claims(context, client, change):
    settings = context[2]
    claims = {
        "sub": "1",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    algorithm = "HS256"
    if change == "expired":
        claims["exp"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    if change == "issuer":
        claims["iss"] = "wrong"
    if change == "audience":
        claims["aud"] = "wrong"
    if change == "algorithm":
        algorithm = "HS512"
    if change == "missing_exp":
        del claims["exp"]
    if change == "unknown_user":
        claims["sub"] = "999"
    token = jwt.encode(claims, settings.jwt_secret, algorithm=algorithm)
    assert (
        client.get("/validate_post", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )


def test_signup_and_login_preserved(client):
    payload = dict(
        full_name="New User",
        email="new@example.invalid",
        password="synthetic-password",
        confirm_password="synthetic-password",
    )
    assert client.post("/signup", json=payload).status_code == 201
    response = client.post(
        "/login",
        json={"email_or_username": "new@example.invalid", "password": "synthetic-password"},
    )
    assert response.status_code == 200
    assert (
        client.get(
            "/validate_post", headers={"Authorization": "Bearer " + response.json["access_token"]}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/login", json={"email_or_username": "user1", "password": "wrong-password"}
        ).status_code
        == 401
    )


def test_drafts_are_owned_and_legacy_quarantined(client, auth):
    response = client.get("/validate_post", headers=auth)
    assert [p["id"] for p in response.json] == [1]
    assert response.json[0]["email_subject"] == "Subject 1"
    assert "Subject 2" not in response.get_data(as_text=True)


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("POST", "/validate_post", {"post_id": 2, "action": "approve"}),
        ("POST", "/validate_post", {"post_id": 2, "action": "reject"}),
        ("POST", "/post/linkedin", {"post_id": 2}),
        ("POST", "/schedule_post", {"post_id": 2, "start_time": "2099-01-01T00:00:00Z"}),
        ("DELETE", "/delete_scheduled_post", {"post_id": 2}),
        ("GET", "/images/2", {}),
    ],
)
def test_other_user_cannot_access(context, client, auth, method, path, payload):
    publisher = Mock()
    context[0].config["LINKEDIN_FACTORY"] = publisher
    response = client.open(path, method=method, headers=auth, json=payload)
    assert response.status_code == 404
    publisher.assert_not_called()
    with context[1]() as db:
        assert db.get(LinkedInPost, 2).status == "Pending"


def test_generation_uses_authenticated_owner(context, client, auth):
    factory = Mock(
        return_value=SimpleNamespace(kickoff=lambda **kwargs: {"post_id": 1, "slogan": "Synthetic"})
    )
    context[0].config["CREW_FACTORY"] = factory
    response = client.post(
        "/run_agents_manual", headers=auth, json={"subject": "Test", "body": "Test", "user_id": 2}
    )
    assert response.status_code == 200
    factory.assert_called_once_with(1)


def test_generation_failure_not_success(context, client, auth):
    context[0].config["CREW_FACTORY"] = Mock(
        return_value=SimpleNamespace(kickoff=lambda: {"error": "No email"})
    )
    assert client.post("/run_agents", headers=auth).status_code == 400


def test_credentials_encrypted_and_owned(context):
    store = context[0].extensions["credential_store"]
    store.save(
        1, "linkedin", {"access_token": "synthetic-oauth-token", "expires_at": time.time() + 3600}
    )
    assert store.load(1, "linkedin")["access_token"] == "synthetic-oauth-token"
    with pytest.raises(SecurityError):
        store.load(2, "linkedin")
    with context[1]() as db:
        assert "synthetic-oauth-token" not in db.query(OAuthCredential).one().encrypted_token


@pytest.mark.parametrize("provider", ["gmail", "linkedin"])
@pytest.mark.parametrize("invalid", ["missing", "wrong", "expired", "browser", "provider"])
def test_invalid_oauth_state(context, provider, invalid):
    factory, settings = context[1:]
    state, browser = issue_state(factory, settings, 1, provider)
    if invalid == "missing":
        state = ""
    if invalid == "wrong":
        state = "synthetic-unknown-state"
    if invalid == "expired":
        with factory.begin() as db:
            db.execute(
                update(OAuthState).values(
                    expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
                    - timedelta(seconds=1)
                )
            )
    if invalid == "browser":
        browser = "different-browser"
    if invalid == "provider":
        provider = "gmail" if provider == "linkedin" else "linkedin"
    with pytest.raises(SecurityError):
        consume_state(factory, provider, state, browser)


@pytest.mark.parametrize("provider", ["gmail", "linkedin"])
def test_oauth_state_single_use(context, provider):
    factory, settings = context[1:]
    state, browser = issue_state(factory, settings, 1, provider)
    assert consume_state(factory, provider, state, browser) == 1
    with pytest.raises(SecurityError):
        consume_state(factory, provider, state, browser)


def test_oauth_callback_and_browser_binding(context, client, auth, monkeypatch):
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "synthetic-client-id")
    exchange = Mock(
        return_value={"access_token": "synthetic-provider-token", "expires_at": time.time() + 3600}
    )
    monkeypatch.setattr(LinkedInPoster, "exchange_code_for_access_token", exchange)
    started = client.get("/auth/linkedin", headers=auth)
    assert started.status_code == 200
    assert (
        "HttpOnly" in started.headers["Set-Cookie"]
        and "SameSite=Lax" in started.headers["Set-Cookie"]
    )
    state = parse_qs(urlsplit(started.json["auth_url"]).query)["state"][0]
    other_browser = context[0].test_client()
    assert (
        other_browser.get(f"/auth/linkedin/callback?state={state}&code=synthetic").status_code
        == 400
    )
    response = client.get(f"/auth/linkedin/callback?state={state}&code=synthetic")
    assert response.status_code == 302
    assert client.get(f"/auth/linkedin/callback?state={state}&code=synthetic").status_code == 400
    exchange.assert_called_once()
    assert (
        context[0].extensions["credential_store"].load(1, "linkedin")["access_token"]
        == "synthetic-provider-token"
    )
    with pytest.raises(SecurityError):
        context[0].extensions["credential_store"].load(2, "linkedin")


def test_callback_denial_consumes_state(context, client):
    state, browser = issue_state(context[1], context[2], 1, "gmail")
    client.set_cookie(state_cookie(state), browser, path="/auth/gmail/callback")
    assert client.get(f"/auth/gmail/callback?state={state}&error=access_denied").status_code == 400
    with pytest.raises(SecurityError):
        consume_state(context[1], "gmail", state, browser)


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "null", "http://127.0.0.1:5500.evil.example"]
)
def test_disallowed_origins(client, auth, origin):
    for method in ("GET", "OPTIONS"):
        response = client.open("/validate_post", method=method, headers={**auth, "Origin": origin})
        assert response.status_code == 403
        assert "Access-Control-Allow-Origin" not in response.headers


def test_trusted_cors_preflight(client):
    response = client.options(
        "/validate_post",
        headers={
            "Origin": "http://127.0.0.1:5500",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5500"
    assert response.headers["Access-Control-Allow-Origin"] != "*"


def registered_image(context, name=None, owner=1, generated=True):
    settings = context[2]
    name = name or ("generated_" + "a" * 32 + ".png")
    buf = io.BytesIO()
    PILImage.new("RGB", (2, 2)).save(buf, format="PNG")
    content = buf.getvalue()
    folder = settings.generated_image_dir / str(owner)
    folder.mkdir(parents=True, exist_ok=True)
    if "/" not in name and "\\" not in name:
        (folder / name).write_bytes(content)
    with context[1].begin() as db:
        image = Image(
            user_id=owner,
            email_id=owner,
            image_path=name,
            is_generated=generated,
            sha256=hashlib.sha256(content).hexdigest(),
        )
        db.add(image)
        db.flush()
        db.get(LinkedInPost, 1).image_id = image.id
        return image.id


@pytest.mark.parametrize(
    "path",
    [
        "../secret.png",
        "/etc/passwd",
        "C:\\private\\file.png",
        "ordinary.png",
        "generated_" + "a" * 32 + ".png/../secret",
    ],
)
def test_invalid_image_paths(context, client, auth, path):
    registered_image(context, name=path)
    publisher = Mock()
    context[0].config["LINKEDIN_FACTORY"] = publisher
    assert (
        client.post(
            "/validate_post", headers=auth, json={"post_id": 1, "action": "approve"}
        ).status_code
        == 400
    )
    publisher.assert_not_called()
    with context[1]() as db:
        assert db.get(LinkedInPost, 1).post_status == "Draft"


@pytest.mark.parametrize("kind", ["other_owner", "unregistered", "modified", "symlink", "missing"])
def test_image_provenance(context, client, auth, kind):
    registered_image(
        context, owner=2 if kind == "other_owner" else 1, generated=kind != "unregistered"
    )
    path = context[2].generated_image_dir / "1" / ("generated_" + "a" * 32 + ".png")
    if kind == "modified":
        path.write_bytes(b"not the registered content")
    if kind == "missing":
        path.unlink()
    if kind == "symlink":
        target = path.parent.parent / "outside.png"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
    assert (
        client.post(
            "/validate_post", headers=auth, json={"post_id": 1, "action": "approve"}
        ).status_code
        == 400
    )


def test_raw_publish_paths_refused(client, auth):
    response = client.post(
        "/post/linkedin",
        headers=auth,
        json={"post_id": 1, "text": "bypass", "image_path": "/etc/passwd"},
    )
    assert response.status_code == 400


def response(status=200, body=None, headers=None):
    fake = Mock(status_code=status, headers=headers or {})
    fake.json.return_value = body or {}
    return fake


def linkedin_client(settings, publication_response=None, error=None):
    http = Mock()
    responses = [
        response(body={"sub": "synthetic-person"}),
        error or publication_response or response(201, {"id": "urn:li:share:synthetic"}),
    ]
    http.request.side_effect = responses
    client = LinkedInPoster(
        settings, {"access_token": "synthetic-token", "expires_at": time.time() + 3600}, http=http
    )
    return client, http


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_linkedin_http_errors(context, status):
    client, http = linkedin_client(context[2], response(status))
    with pytest.raises(LinkedInError) as caught:
        client.post_to_linkedin("Synthetic post")
    assert caught.value.status_code == status
    assert caught.value.uncertain == (status >= 500)
    for call in http.request.call_args_list:
        assert call.kwargs["timeout"] == (5, 30)
        assert call.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError()])
def test_network_failures(context, error):
    client, _ = linkedin_client(context[2], error=error)
    with pytest.raises(LinkedInError) as caught:
        client.post_to_linkedin("Synthetic post")
    assert caught.value.uncertain


@pytest.mark.parametrize("stage", ["profile", "registration", "upload"])
@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_linkedin_failures_before_publication(context, stage, status):
    http = Mock()
    replies = []
    if stage != "profile":
        replies.append(response(body={"sub": "synthetic-person"}))
    if stage == "upload":
        replies.append(
            response(
                body={
                    "value": {
                        "asset": "urn:li:digitalmediaAsset:synthetic",
                        "uploadMechanism": {
                            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest": {
                                "uploadUrl": "https://www.linkedin.com/upload"
                            }
                        },
                    }
                }
            )
        )
    replies.append(response(status))
    http.request.side_effect = replies
    client = LinkedInPoster(
        context[2], {"access_token": "synthetic", "expires_at": time.time() + 3600}, http
    )
    with pytest.raises(LinkedInError):
        client.post_to_linkedin("Synthetic", b"validated bytes")
    assert all(call.args[1] != LinkedInPoster.POST_URL for call in http.request.call_args_list)


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_publication_failure_never_published(context, client, auth, status):
    poster, http = linkedin_client(context[2], response(status))
    context[0].config["LINKEDIN_FACTORY"] = lambda uid: poster
    result = client.post("/validate_post", headers=auth, json={"post_id": 1, "action": "approve"})
    assert result.status_code == 502
    with context[1]() as db:
        post = db.get(LinkedInPost, 1)
        assert post.post_status == ("PublicationUnknown" if status >= 500 else "Failed")
        assert post.linkedin_post_id is None
    count = http.request.call_count
    assert (
        client.post(
            "/validate_post", headers=auth, json={"post_id": 1, "action": "approve"}
        ).status_code
        == 409
    )
    assert client.post("/post/linkedin", headers=auth, json={"post_id": 1}).status_code == 409
    assert http.request.call_count == count


@pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError()])
def test_network_failure_never_published(context, client, auth, error):
    poster, http = linkedin_client(context[2], error=error)
    context[0].config["LINKEDIN_FACTORY"] = lambda uid: poster
    assert (
        client.post(
            "/validate_post", headers=auth, json={"post_id": 1, "action": "approve"}
        ).status_code
        == 502
    )
    with context[1]() as db:
        assert db.get(LinkedInPost, 1).post_status == "PublicationUnknown"
    assert client.post("/post/linkedin", headers=auth, json={"post_id": 1}).status_code == 409
    assert http.request.call_count == 2


def test_success_and_duplicate_approval(context, client, auth):
    poster, http = linkedin_client(context[2])
    context[0].config["LINKEDIN_FACTORY"] = lambda uid: poster
    result = client.post("/validate_post", headers=auth, json={"post_id": 1, "action": "approve"})
    assert result.status_code == 200
    with context[1]() as db:
        post = db.get(LinkedInPost, 1)
        assert post.post_status == "Published"
        assert post.linkedin_post_id == "urn:li:share:synthetic"
    assert (
        client.post(
            "/validate_post", headers=auth, json={"post_id": 1, "action": "approve"}
        ).status_code
        == 409
    )
    assert client.post("/post/linkedin", headers=auth, json={"post_id": 1}).status_code == 409
    assert http.request.call_count == 2


def test_verified_image_publish(context, client, auth):
    image_id = registered_image(context)
    poster = Mock()
    poster.post_to_linkedin.return_value = {"id": "synthetic-post-id"}
    context[0].config["LINKEDIN_FACTORY"] = lambda uid: poster
    assert client.get(f"/images/{image_id}", headers=auth).status_code == 200
    assert (
        client.post(
            "/validate_post", headers=auth, json={"post_id": 1, "action": "approve"}
        ).status_code
        == 200
    )
    assert poster.post_to_linkedin.call_args.args[1].startswith(b"\x89PNG")


@pytest.mark.parametrize(
    "result", [response(200, {"id": "synthetic"}), response(201), response(302)]
)
def test_unconfirmed_publication(context, result):
    poster, _ = linkedin_client(context[2], result)
    with pytest.raises(LinkedInError):
        poster.post_to_linkedin("Synthetic")


def test_201_header_confirmation(context):
    poster, _ = linkedin_client(context[2], response(201, headers={"X-RestLi-Id": "synthetic-id"}))
    assert poster.post_to_linkedin("Synthetic")["id"] == "synthetic-id"


def test_concurrent_publish_claim(context):
    app, factory, settings = context
    with factory.begin() as db:
        db.get(LinkedInPost, 1).status = "Approved"
    started, release = threading.Event(), threading.Event()

    def perform(*args):
        started.set()
        assert release.wait(5)
        return {"id": "synthetic-one-publication"}

    poster = Mock()
    poster.post_to_linkedin.side_effect = perform
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(publish_post, factory, settings, 1, 1, lambda uid: poster)
        assert started.wait(5)
        try:
            with pytest.raises(PostConflict):
                publish_post(factory, settings, 1, 1, lambda uid: poster)
        finally:
            release.set()
        assert first.result()["id"] == "synthetic-one-publication"
    poster.post_to_linkedin.assert_called_once()


def test_scheduler_only_owned_approved_and_no_retry(context):
    app, factory, _ = context
    with factory.begin() as db:
        for i in (1, 2, 3):
            post = db.get(LinkedInPost, i)
            post.post_status = "Scheduled"
            post.posted_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
            post.status = "Approved" if i in (1, 3) else "Rejected"
    poster = Mock()
    poster.post_to_linkedin.side_effect = LinkedInError("publication", 500, True)
    creator = Mock(return_value=poster)
    app.config["LINKEDIN_FACTORY"] = creator
    publish_scheduled_posts(app)
    publish_scheduled_posts(app)
    creator.assert_called_once_with(1)
    with factory() as db:
        assert db.get(LinkedInPost, 1).post_status == "PublicationUnknown"
        assert db.get(LinkedInPost, 2).post_status == "Scheduled"
        assert db.get(LinkedInPost, 3).post_status == "Scheduled"


def test_schedule_and_cancel_owned_post(context, client, auth):
    calendar = Mock()
    calendar.schedule_post.return_value = {"id": "synthetic-event"}
    context[0].config["GMAIL_FACTORY"] = Mock(return_value=calendar)
    assert (
        client.post(
            "/schedule_post",
            headers=auth,
            json={"post_id": 1, "start_time": "2099-01-01T00:00:00Z"},
        ).status_code
        == 200
    )
    with context[1]() as db:
        assert db.get(LinkedInPost, 1).google_calendar_event_id == "synthetic-event"
    assert [e["post_id"] for e in client.get("/upcoming_events", headers=auth).json["events"]] == [
        1
    ]
    assert (
        client.delete("/delete_scheduled_post", headers=auth, json={"post_id": 1}).status_code
        == 200
    )
    calendar.delete_event.assert_called_once_with("synthetic-event")


def test_safe_errors(context, client, auth):
    context[0].config["CREW_FACTORY"] = Mock(
        side_effect=RuntimeError("synthetic-confidential-marker")
    )
    response = client.post("/run_agents", headers=auth)
    assert response.status_code == 500
    assert "synthetic-confidential-marker" not in response.get_data(as_text=True)


@pytest.mark.parametrize(
    "missing", ["DATABASE_URL", "JWT_SECRET_KEY", "TOKEN_ENCRYPTION_KEY", "FRONTEND_ORIGINS"]
)
def test_missing_configuration(monkeypatch, context, missing):
    monkeypatch.setattr("slogancraftai.settings.load_dotenv", lambda **kwargs: None)
    for name, value in {
        "DATABASE_URL": "sqlite://",
        "JWT_SECRET_KEY": context[2].jwt_secret,
        "TOKEN_ENCRYPTION_KEY": context[2].token_encryption_key,
        "FRONTEND_ORIGINS": "http://127.0.0.1:5500",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(ConfigurationError, match=missing):
        Settings.from_env()


def test_debug_is_disabled(context):
    assert context[0].debug is False


def test_gmail_callback_stores_tokens_for_initiating_user(context, client, auth, monkeypatch):
    from slogancraftai.tools.read_mail import GmailTool

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "synthetic-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "synthetic-client-secret")
    flow = Mock()
    flow.credentials.to_json.return_value = json.dumps(
        {"token": "synthetic-google-token", "refresh_token": "synthetic-refresh"}
    )
    started = client.get("/auth/gmail", headers=auth)
    assert started.status_code == 200
    state = parse_qs(urlsplit(started.json["auth_url"]).query)["state"][0]
    monkeypatch.setattr(GmailTool, "_flow", lambda self: flow)
    assert client.get(f"/auth/gmail/callback?state={state}&code=synthetic").status_code == 302
    assert client.get(f"/auth/gmail/callback?state={state}&code=synthetic").status_code == 400
    flow.fetch_token.assert_called_once_with(code="synthetic", timeout=context[2].request_timeout)
    store = context[0].extensions["credential_store"]
    assert store.load(1, "gmail")["token"] == "synthetic-google-token"
    with pytest.raises(SecurityError):
        store.load(2, "gmail")


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.example.com",
        "http://localhost:bad",
        "http://localhost:99999",
        "http://[invalid",
    ],
)
def test_invalid_configured_origins(origin):
    from slogancraftai.settings import valid_origin

    assert not valid_origin(origin)


def test_access_log_omits_oauth_query_parameters():
    from slogancraftai.main import PrivateRequestHandler

    handler = object.__new__(PrivateRequestHandler)
    handler.path = (
        "/auth/linkedin/callback?code=synthetic-private-code&state=synthetic-private-state"
    )
    handler.command = "GET"
    handler.log = Mock()
    handler.log_request(302, 0)
    rendered = str(handler.log.call_args)
    assert "/auth/linkedin/callback" in rendered
    assert "synthetic-private" not in rendered


def test_entrypoint_binds_locally_without_debug_or_reloader(context, monkeypatch):
    import slogancraftai.main as main

    app = context[0]
    scheduler = Mock()
    monkeypatch.setattr("apscheduler.schedulers.background.BackgroundScheduler", lambda: scheduler)
    monkeypatch.setattr(main, "create_app", lambda: app)
    run = Mock()
    monkeypatch.setattr(app, "run", run)
    main.serve()
    run.assert_called_once_with(
        debug=False,
        host="127.0.0.1",
        port=5000,
        use_reloader=False,
        request_handler=main.PrivateRequestHandler,
    )
    scheduler.start.assert_called_once()
    scheduler.shutdown.assert_called_once_with(wait=False)
