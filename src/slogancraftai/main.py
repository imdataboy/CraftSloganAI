"""Existing Flask API with authenticated, owner-scoped operational routes."""

from datetime import datetime, timedelta, timezone
from functools import partial

from flask import Flask, Response, g, jsonify, redirect, request
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException
from werkzeug.serving import WSGIRequestHandler

from .auth_utils import (
    create_access_token,
    hash_password,
    require_auth,
    verify_password,
)
from .db import create_session_factory
from .models import Image, LinkedInPost, User
from .publishing import PostConflict, publish_post
from .security import (
    CredentialStore,
    SecurityError,
    consume_state,
    generated_image_bytes,
    issue_state,
    state_cookie,
)
from .settings import ConfigurationError, Settings
from .tools.linkedin_poster import LinkedInError, LinkedInPoster
from .tools.read_mail import GmailTool


class PrivateRequestHandler(WSGIRequestHandler):
    """Do not write OAuth authorization codes or state values to access logs."""

    def log_request(self, code="-", size="-"):
        path = getattr(self, "path", "/").split("?", 1)[0]
        path = path.translate(self._control_char_table)
        self.log("info", '"%s %s" %s %s', getattr(self, "command", "-"), path, code, size)


def create_app(settings=None, session_factory=None):
    settings = settings or Settings.from_env()
    app = Flask(__name__)
    app.config.update(SETTINGS=settings, DEBUG=False, MAX_CONTENT_LENGTH=256 * 1024)
    if session_factory is None:
        session_factory, engine = create_session_factory(settings.database_url)
        app.extensions["database_engine"] = engine
    app.config["SESSION_FACTORY"] = session_factory
    store = CredentialStore(session_factory, settings)
    app.extensions["credential_store"] = store
    app.config["LINKEDIN_FACTORY"] = lambda user_id: LinkedInPoster(
        settings, store.load(user_id, "linkedin")
    )

    def gmail_factory(user_id, require_token=True):
        try:
            token = store.load(user_id, "gmail")
        except SecurityError:
            if require_token:
                raise
            token = None
        return GmailTool(settings, token, partial(store.save, user_id, "gmail"))

    app.config["GMAIL_FACTORY"] = gmail_factory

    def crew_factory(user_id):
        # Importing the security/API layer must not initialize agents or make LLM calls.
        from .crew import Slogancraftai

        return Slogancraftai(
            settings, session_factory, user_id, app.config["GMAIL_FACTORY"](user_id, False)
        )

    app.config["CREW_FACTORY"] = crew_factory

    @app.before_request
    def check_origin():
        origin = request.headers.get("Origin")
        if origin and origin not in settings.frontend_origins:
            return jsonify(error="Origin is not permitted."), 403
        if request.method == "OPTIONS":
            return "", 204

    @app.after_request
    def response_security(response):
        origin = request.headers.get("Origin")
        if origin in settings.frontend_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
            response.vary.add("Origin")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.errorhandler(Exception)
    def safe_error(exc):
        if isinstance(exc, HTTPException):
            return jsonify(error=exc.description), exc.code
        if isinstance(exc, ConfigurationError):
            return jsonify(error=str(exc)), 503
        if isinstance(exc, SecurityError):
            return jsonify(error=str(exc)), 400
        if isinstance(exc, PostConflict):
            return jsonify(error=str(exc)), 409
        if isinstance(exc, LookupError):
            return jsonify(error="Resource not found."), 404
        if isinstance(exc, LinkedInError):
            return jsonify(error=str(exc), publication_uncertain=exc.uncertain), 502
        # Exception text and tracebacks may contain credentials/provider payloads.
        app.logger.error("Operation failed (%s).", type(exc).__name__)
        return jsonify(error="Operation failed. No successful outcome has been confirmed."), 500

    def data():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise SecurityError("A JSON object is required.")
        return value

    def post_id(payload):
        value = payload.get("post_id")
        if type(value) is not int or value <= 0:
            raise SecurityError("A positive integer post_id is required.")
        return value

    def owned_post(db, identifier):
        post = db.query(LinkedInPost).filter_by(id=identifier, user_id=g.user_id).first()
        if post is None:
            raise LookupError()
        return post

    def publish(identifier, user_id=None):
        return publish_post(
            session_factory,
            settings,
            user_id or g.user_id,
            identifier,
            app.config["LINKEDIN_FACTORY"],
        )

    @app.route("/")
    def home():
        return jsonify(message="SloganCraftAI API. Operational requests require a Bearer token.")

    @app.route("/signup", methods=["POST"])
    def signup():
        payload = data()
        for key in ("full_name", "email", "password", "confirm_password"):
            if not isinstance(payload.get(key), str) or not payload[key].strip():
                raise SecurityError("All signup fields are required.")
        if payload["password"] != payload["confirm_password"]:
            raise SecurityError("Passwords do not match.")
        try:
            password_hash = hash_password(payload["password"])
        except ValueError as exc:
            raise SecurityError(str(exc)) from None
        with session_factory() as db:
            base = "".join(payload["full_name"].split())[:80]
            username, suffix = base, 1
            while db.query(User.id).filter_by(username=username).first():
                username = f"{base}{suffix}"
                suffix += 1
            db.add(
                User(
                    full_name=payload["full_name"].strip(),
                    email=payload["email"].strip().lower(),
                    username=username,
                    password_hash=password_hash,
                )
            )
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return jsonify(error="Account details are already registered."), 400
        return jsonify(message="User registered successfully", username=username), 201

    @app.route("/login", methods=["POST"])
    def login():
        payload = data()
        name, password = payload.get("email_or_username"), payload.get("password")
        if not isinstance(name, str) or not isinstance(password, str):
            raise SecurityError("Email/username and password are required.")
        with session_factory() as db:
            user = (
                db.query(User)
                .filter((User.email == name.strip().lower()) | (User.username == name.strip()))
                .first()
            )
            if user is None or not verify_password(password, user.password_hash):
                return jsonify(error="Invalid credentials"), 401
            token = create_access_token({"user_id": user.id}, settings)
        return jsonify(message="Login successful", access_token=token)

    @app.route("/run_agents", methods=["POST"])
    @require_auth
    def run():
        result = app.config["CREW_FACTORY"](g.user_id).kickoff()
        if not isinstance(result, dict) or result.get("error") or not result.get("post_id"):
            raise SecurityError("No complete draft was generated.")
        return jsonify(message="Draft generated successfully", result=result)

    @app.route("/run_agents_manual", methods=["POST"])
    @require_auth
    def run_agents_manual():
        payload = data()
        if any(
            not isinstance(payload.get(k), str) or not payload[k].strip()
            for k in ("subject", "body")
        ):
            raise SecurityError("Both subject and body are required.")
        result = app.config["CREW_FACTORY"](g.user_id).kickoff(
            manual_email={
                "subject": payload["subject"],
                "body": payload["body"],
                "sender": str(payload.get("sender", "Manual input")),
            }
        )
        if not isinstance(result, dict) or result.get("error") or not result.get("post_id"):
            raise SecurityError("No complete draft was generated.")
        return jsonify(message="Draft generated successfully", result=result)

    @app.route("/auth/<provider>", methods=["GET"])
    @require_auth
    def start_oauth(provider):
        if provider not in ("gmail", "linkedin"):
            raise LookupError()
        state, browser = issue_state(session_factory, settings, g.user_id, provider)
        client = (
            LinkedInPoster(settings)
            if provider == "linkedin"
            else app.config["GMAIL_FACTORY"](g.user_id, False)
        )
        response = jsonify(auth_url=client.get_auth_url(state))
        response.set_cookie(
            state_cookie(state),
            browser,
            max_age=settings.oauth_lifetime_seconds,
            httponly=True,
            secure=settings.backend_url.startswith("https:"),
            samesite="Lax",
            path=f"/auth/{provider}/callback",
        )
        return response

    @app.route("/auth/<provider>/callback")
    def oauth_callback(provider):
        if provider not in ("gmail", "linkedin"):
            raise LookupError()
        state = request.args.get("state", "")
        user_id = consume_state(
            session_factory, provider, state, request.cookies.get(state_cookie(state))
        )
        # Consume even when the provider denies access. No state may be replayed.
        code = request.args.get("code")
        if not code or request.args.get("error"):
            raise SecurityError("OAuth authorization was not completed. Start a new connection.")
        if provider == "linkedin":
            store.save(
                user_id, provider, LinkedInPoster(settings).exchange_code_for_access_token(code)
            )
        else:
            app.config["GMAIL_FACTORY"](user_id, False).exchange_code_for_tokens(code)
        response = redirect(f"{settings.frontend_url}/run.html")
        response.delete_cookie(state_cookie(state), path=f"/auth/{provider}/callback")
        return response

    @app.route("/auth/<provider>/status")
    @require_auth
    def oauth_status(provider):
        if provider not in ("gmail", "linkedin"):
            raise LookupError()
        try:
            client = (
                app.config["LINKEDIN_FACTORY"](g.user_id)
                if provider == "linkedin"
                else app.config["GMAIL_FACTORY"](g.user_id)
            )
            connected = client.is_authenticated()
        except SecurityError:
            connected = False
        return jsonify(connected=connected)

    @app.route("/validate_post", methods=["GET", "POST"])
    @require_auth
    def validate_post():
        if request.method == "GET":
            with session_factory() as db:
                posts = db.query(LinkedInPost).filter_by(user_id=g.user_id, status="Pending").all()
                return jsonify(
                    [
                        {
                            "id": p.id,
                            "email_id": p.email_id,
                            "email_subject": p.email.email_subject
                            if p.email and p.email.user_id == g.user_id
                            else "Unknown",
                            "image_id": p.image_id,
                            "image_path": f"/images/{p.image_id}"
                            if p.image and p.image.user_id == g.user_id
                            else None,
                            "post_text": p.post_text,
                            "status": p.status,
                            "created_at": p.posted_at.isoformat() if p.posted_at else None,
                        }
                        for p in posts
                    ]
                )
        payload = data()
        identifier = post_id(payload)
        action = payload.get("action")
        if action == "reject":
            with session_factory.begin() as db:
                post = owned_post(db, identifier)
                count = db.execute(
                    update(LinkedInPost)
                    .where(
                        LinkedInPost.id == post.id,
                        LinkedInPost.user_id == g.user_id,
                        LinkedInPost.status == "Pending",
                        LinkedInPost.post_status == "Draft",
                    )
                    .values(status="Rejected")
                ).rowcount
                if count != 1:
                    raise PostConflict("Only pending drafts may be rejected.")
            return jsonify(message="Post rejected successfully")
        if action != "approve":
            raise SecurityError("Invalid action.")
        return approve(identifier, payload.get("schedule_time"))

    def approve(identifier, schedule_time=None):
        start = None
        if schedule_time:
            try:
                start = datetime.fromisoformat(schedule_time.replace("Z", "+00:00"))
                if start.tzinfo is None or start <= datetime.now(timezone.utc):
                    raise ValueError()
                start = start.astimezone(timezone.utc)
            except (ValueError, TypeError, AttributeError):
                raise SecurityError(
                    "Schedule time must be in the future and include a timezone."
                ) from None
        with session_factory.begin() as db:
            post = owned_post(db, identifier)
            if post.image_id is not None:
                generated_image_bytes(post.image, g.user_id, settings)
            count = db.execute(
                update(LinkedInPost)
                .where(
                    LinkedInPost.id == identifier,
                    LinkedInPost.user_id == g.user_id,
                    LinkedInPost.status == "Pending",
                    LinkedInPost.post_status == "Draft",
                )
                .values(status="Approved", post_status="Scheduling" if start else "Draft")
            ).rowcount
            if count != 1:
                raise PostConflict("Post has already been reviewed or attempted.")
            text = post.post_text
        if start:
            try:
                event = app.config["GMAIL_FACTORY"](g.user_id).schedule_post(
                    f"Scheduled LinkedIn Post - {identifier}",
                    text,
                    start.isoformat(),
                    (start + timedelta(minutes=10)).isoformat(),
                    "UTC",
                )
                if not isinstance(event, dict) or not event.get("id"):
                    raise SecurityError("Calendar did not confirm the event.")
                with session_factory.begin() as db:
                    db.execute(
                        update(LinkedInPost)
                        .where(
                            LinkedInPost.id == identifier,
                            LinkedInPost.user_id == g.user_id,
                            LinkedInPost.post_status == "Scheduling",
                        )
                        .values(
                            post_status="Scheduled",
                            posted_at=start.replace(tzinfo=None),
                            google_calendar_event_id=event["id"],
                        )
                    )
                return jsonify(message="Post scheduled successfully")
            except Exception:
                with session_factory.begin() as db:
                    db.execute(
                        update(LinkedInPost)
                        .where(
                            LinkedInPost.id == identifier,
                            LinkedInPost.user_id == g.user_id,
                            LinkedInPost.post_status == "Scheduling",
                        )
                        .values(post_status="ScheduleUnknown")
                    )
                raise SecurityError(
                    "Scheduling was not confirmed. Reconcile the Calendar event before retrying."
                ) from None
        result = publish(identifier)
        return jsonify(message="Post published successfully", linkedin_post_id=result["id"])

    @app.route("/post/linkedin", methods=["POST"])
    @require_auth
    def post_linkedin():
        payload = data()
        if "image_path" in payload or "text" in payload:
            raise SecurityError(
                "Publish an approved post_id; raw text and filesystem paths are not accepted."
            )
        result = publish(post_id(payload))
        return jsonify(message="Post published successfully", linkedin_post_id=result["id"])

    @app.route("/schedule_post", methods=["POST"])
    @require_auth
    def schedule_post():
        payload = data()
        return (
            approve(post_id(payload), payload.get("start_time"))
            if payload.get("start_time")
            else (jsonify(error="start_time is required."), 400)
        )

    @app.route("/upcoming_events")
    @require_auth
    def upcoming_events():
        # Only expose events associated with this application's owned posts.
        with session_factory() as db:
            posts = (
                db.query(LinkedInPost).filter_by(user_id=g.user_id, post_status="Scheduled").all()
            )
            return jsonify(
                events=[
                    {
                        "post_id": p.id,
                        "summary": f"Scheduled LinkedIn Post - {p.id}",
                        "start": p.posted_at.isoformat() + "Z",
                        "description": p.post_text,
                    }
                    for p in posts
                ]
            )

    @app.route("/delete_scheduled_post", methods=["DELETE"])
    @require_auth
    def delete_scheduled_post():
        identifier = post_id(data())
        with session_factory.begin() as db:
            post = owned_post(db, identifier)
            event_id = post.google_calendar_event_id
            count = db.execute(
                update(LinkedInPost)
                .where(
                    LinkedInPost.id == identifier,
                    LinkedInPost.user_id == g.user_id,
                    LinkedInPost.post_status == "Scheduled",
                )
                .values(post_status="Cancelling")
            ).rowcount
            if count != 1:
                raise PostConflict("Post is not scheduled or another action is in progress.")
        try:
            if event_id:
                app.config["GMAIL_FACTORY"](g.user_id).delete_event(event_id)
        except Exception:
            # Leave Cancelling to block publication until the provider is reconciled.
            raise SecurityError(
                "Cancellation was not confirmed; reconcile the Calendar event."
            ) from None
        with session_factory.begin() as db:
            db.query(LinkedInPost).filter_by(
                id=identifier, user_id=g.user_id, post_status="Cancelling"
            ).delete()
        return jsonify(message="Scheduled post deleted successfully")

    @app.route("/images/<int:image_id>")
    @require_auth
    def serve_image(image_id):
        with session_factory() as db:
            image = db.query(Image).filter_by(id=image_id, user_id=g.user_id).first()
            if image is None:
                raise LookupError()
            content = generated_image_bytes(image, g.user_id, settings)
        return Response(content, mimetype="image/png")

    @app.route("/chat", methods=["POST"])
    @require_auth
    def chat():
        # Preserve CraftBot while keeping the provider key out of browser JavaScript.
        import requests

        prompt = data().get("message")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20000:
            raise SecurityError("A message of at most 20000 characters is required.")
        model = settings.provider_value("GEMINI_MODEL")
        if not all(c.isalnum() or c in "-._" for c in model):
            raise ConfigurationError("GEMINI_MODEL is invalid.")
        try:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": settings.provider_value("GEMINI_API_KEY")},
                json={"contents": [{"role": "user", "parts": [{"text": prompt}]}]},
                timeout=settings.request_timeout,
            )
            response.raise_for_status()
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except ConfigurationError:
            raise
        except Exception:
            return jsonify(error="Chat provider request failed."), 502
        return jsonify(text=text)

    return app


def publish_scheduled_posts(app):
    factory = app.config["SESSION_FACTORY"]
    with factory() as db:
        posts = (
            db.query(LinkedInPost.id, LinkedInPost.user_id)
            .filter(
                LinkedInPost.user_id.is_not(None),
                LinkedInPost.status == "Approved",
                LinkedInPost.post_status == "Scheduled",
                LinkedInPost.posted_at <= datetime.now(timezone.utc).replace(tzinfo=None),
            )
            .all()
        )
    for identifier, user_id in posts:
        try:
            publish_post(
                factory, app.config["SETTINGS"], user_id, identifier, app.config["LINKEDIN_FACTORY"]
            )
        except Exception as exc:
            app.logger.warning(
                "Scheduled post %s not confirmed (%s).", identifier, type(exc).__name__
            )


def serve():
    from apscheduler.schedulers.background import BackgroundScheduler

    app = create_app()
    scheduler = BackgroundScheduler()
    scheduler.add_job(publish_scheduled_posts, "interval", seconds=60, args=[app], max_instances=1)
    scheduler.start()
    try:
        app.run(
            debug=False,
            host="127.0.0.1",
            port=5000,
            use_reloader=False,
            request_handler=PrivateRequestHandler,
        )
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    serve()
