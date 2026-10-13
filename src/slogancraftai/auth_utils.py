from datetime import datetime, timedelta, timezone
from functools import wraps

import bcrypt
import jwt
from flask import current_app, g, jsonify, request

from .models import User


def hash_password(password):
    if not isinstance(password, str) or not 8 <= len(password.encode("utf-8")) <= 72:
        raise ValueError("Password must contain between 8 and 72 UTF-8 bytes.")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password, hashed_password):
    try:
        return len(plain_password.encode()) <= 72 and bcrypt.checkpw(
            plain_password.encode(), hashed_password.encode()
        )
    except (ValueError, TypeError, AttributeError):
        return False


def create_access_token(data, settings=None):
    settings = settings or current_app.config["SETTINGS"]
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(data["user_id"]),
            "iat": now,
            "exp": now + timedelta(seconds=settings.jwt_lifetime_seconds),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def decode_access_token(token, settings=None):
    settings = settings or current_app.config["SETTINGS"]
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        options={"require": ["sub", "exp", "iat", "iss", "aud"]},
    )


def require_auth(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        try:
            scheme, token = header.split(" ", 1)
            if scheme != "Bearer" or not token:
                raise ValueError()
            claims = decode_access_token(token)
            user_id = int(claims["sub"])
            if user_id <= 0:
                raise ValueError()
            with current_app.config["SESSION_FACTORY"]() as db:
                if db.get(User, user_id) is None:
                    raise ValueError()
            g.user_id = user_id
        except (jwt.InvalidTokenError, ValueError, KeyError, TypeError):
            return jsonify(error="A valid Bearer token is required."), 401
        return fn(*args, **kwargs)

    return wrapped
