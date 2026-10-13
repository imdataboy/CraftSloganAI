"""Central environment configuration; never include credential values in errors."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from dotenv import load_dotenv


class ConfigurationError(ValueError):
    pass


def required(name):
    value = os.getenv(name, "").strip()
    if not value or value.lower().startswith(("replace", "your_", "change", "<")):
        raise ConfigurationError(f"{name} must be configured in the environment.")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    token_encryption_key: str
    frontend_origins: tuple
    frontend_url: str
    backend_url: str
    generated_image_dir: Path
    jwt_issuer: str = "slogancraftai"
    jwt_audience: str = "slogancraftai-api"
    jwt_lifetime_seconds: int = 3600
    oauth_lifetime_seconds: int = 600
    request_timeout: tuple = (5, 30)

    @classmethod
    def from_env(cls):
        load_dotenv(override=False)
        secret = required("JWT_SECRET_KEY")
        if len(secret) < 32:
            raise ConfigurationError("JWT_SECRET_KEY must contain at least 32 characters.")
        encryption_key = required("TOKEN_ENCRYPTION_KEY")
        try:
            Fernet(encryption_key.encode())
        except (ValueError, TypeError):
            raise ConfigurationError("TOKEN_ENCRYPTION_KEY must be a valid Fernet key.") from None
        origins = tuple(
            x.strip().rstrip("/") for x in required("FRONTEND_ORIGINS").split(",") if x.strip()
        )
        if not origins or any(not valid_origin(x) for x in origins):
            raise ConfigurationError(
                "FRONTEND_ORIGINS must list explicit HTTP(S) origins without paths or wildcards."
            )
        frontend = os.getenv("FRONTEND_URL", origins[0]).rstrip("/")
        backend = os.getenv("BACKEND_URL", "http://127.0.0.1:5000").rstrip("/")
        if frontend not in origins or not valid_origin(backend):
            raise ConfigurationError(
                "FRONTEND_URL must be trusted; BACKEND_URL must be an explicit HTTP(S) origin."
            )
        return cls(
            required("DATABASE_URL"),
            secret,
            encryption_key,
            origins,
            frontend,
            backend,
            Path(os.getenv("GENERATED_IMAGE_DIR", "generated_images")).resolve(),
        )

    def provider_value(self, name):
        return required(name)

    def redirect_uri(self, provider):
        return f"{self.backend_url}/auth/{provider}/callback"


def valid_origin(value):
    try:
        parsed = urlsplit(value)
        parsed.port  # Reject malformed or out-of-range ports.
    except ValueError:
        return False
    return (
        parsed.scheme in ("http", "https")
        and bool(parsed.hostname)
        and not parsed.username
        and not parsed.password
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and "*" not in value
    )
