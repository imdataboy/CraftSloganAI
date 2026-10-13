"""User-scoped encrypted OAuth storage, one-use state, and generated images."""

import hashlib
import io
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from PIL import Image as PILImage
from sqlalchemy import update

from .models import OAuthCredential, OAuthState


class SecurityError(ValueError):
    pass


class CredentialStore:
    def __init__(self, factory, settings):
        self.factory = factory
        self.cipher = Fernet(settings.token_encryption_key.encode())

    def load(self, user_id, provider):
        with self.factory() as db:
            row = db.query(OAuthCredential).filter_by(user_id=user_id, provider=provider).first()
            if row is None:
                raise SecurityError(f"Connect {provider} before using this operation.")
            try:
                return json.loads(self.cipher.decrypt(row.encrypted_token.encode()))
            except (InvalidToken, ValueError):
                raise SecurityError(
                    f"Reconnect {provider}; stored credentials cannot be read."
                ) from None

    def save(self, user_id, provider, token):
        encrypted = self.cipher.encrypt(json.dumps(token).encode()).decode()
        with self.factory.begin() as db:
            row = db.query(OAuthCredential).filter_by(user_id=user_id, provider=provider).first()
            if row is None:
                row = OAuthCredential(user_id=user_id, provider=provider)
                db.add(row)
            row.encrypted_token = encrypted


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def issue_state(factory, settings, user_id, provider):
    state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with factory.begin() as db:
        db.add(
            OAuthState(
                state_hash=digest(state),
                browser_hash=digest(browser),
                user_id=user_id,
                provider=provider,
                expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
                + timedelta(seconds=settings.oauth_lifetime_seconds),
            )
        )
    return state, browser


def state_cookie(state):
    return "oauth_" + digest(state)[:24]


def consume_state(factory, provider, state, browser):
    if not state or not browser or len(state) > 128 or len(browser) > 128:
        raise SecurityError("Invalid, expired, or already used OAuth state.")
    with factory.begin() as db:
        stmt = (
            update(OAuthState)
            .where(
                OAuthState.state_hash == digest(state),
                OAuthState.browser_hash == digest(browser),
                OAuthState.provider == provider,
                OAuthState.expires_at > datetime.now(timezone.utc).replace(tzinfo=None),
                OAuthState.consumed_at.is_(None),
            )
            .values(consumed_at=datetime.now(timezone.utc).replace(tzinfo=None))
            .returning(OAuthState.user_id)
        )
        user_id = db.execute(stmt).scalar_one_or_none()
        if user_id is None:
            raise SecurityError("Invalid, expired, or already used OAuth state.")
        return user_id


def generated_image_bytes(image, user_id, settings):
    """Accept only an owned, registered generated PNG; never accept caller paths."""
    if image is None or image.user_id != user_id or not image.is_generated:
        raise SecurityError("An owned application-generated image is required.")
    name = image.image_path or ""
    if not re.fullmatch(r"generated_[0-9a-f]{32}\.png", name):
        raise SecurityError("Invalid generated image path.")
    root = Path(settings.generated_image_dir).resolve()
    folder = root / str(user_id)
    path = folder / name
    if (
        folder.is_symlink()
        or path.is_symlink()
        or not path.is_file()
        or path.resolve().parent != folder
    ):
        raise SecurityError("Invalid generated image path.")
    # The generated directory must be private to the application OS account.
    if path.stat().st_size > 10 * 1024 * 1024:
        raise SecurityError("Generated image exceeds the upload limit.")
    data = path.read_bytes()
    if not image.sha256 or not secrets.compare_digest(
        hashlib.sha256(data).hexdigest(), image.sha256
    ):
        raise SecurityError("Generated image content does not match its registered digest.")
    try:
        with PILImage.open(io.BytesIO(data)) as decoded:
            if decoded.format != "PNG":
                raise ValueError()
            decoded.verify()
    except Exception:
        raise SecurityError("Invalid generated PNG image.") from None
    return data
