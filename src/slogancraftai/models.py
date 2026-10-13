from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .db import Base


class Email(Base):
    __tablename__ = "emails"

    # NULL owners quarantine legacy records until an administrator assigns them.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    id = Column(Integer, primary_key=True, index=True)
    email_subject = Column(String, index=True)
    email_body = Column(Text)
    sender = Column(String)
    received_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    processed = Column(Boolean, default=False)

    slogans = relationship("Slogan", back_populates="email")
    images = relationship("Image", back_populates="email")
    linkedin_posts = relationship("LinkedInPost", back_populates="email")


class Slogan(Base):
    __tablename__ = "slogans"

    # NULL owners quarantine legacy records until an administrator assigns them.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"))
    slogan_text = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    used_in_post = Column(Boolean, default=False)

    email = relationship("Email", back_populates="slogans")


class Image(Base):
    __tablename__ = "images"

    # NULL owners quarantine legacy records until an administrator assigns them.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"))
    description = Column(Text)
    image_path = Column(String, nullable=True)
    image_data = Column(LargeBinary, nullable=True)
    is_generated = Column(Boolean, nullable=False, default=False, server_default="false")
    sha256 = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    used_in_post = Column(Boolean, default=False)

    email = relationship("Email", back_populates="images")


class LinkedInPost(Base):
    __tablename__ = "linkedin_posts"

    # NULL owners quarantine legacy records until an administrator assigns them.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"))
    slogan_id = Column(Integer, ForeignKey("slogans.id"), nullable=True)
    image_id = Column(Integer, ForeignKey("images.id"), nullable=True)
    post_text = Column(Text)
    post_status = Column(String)
    status = Column(String, default="Pending")
    posted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    google_calendar_event_id = Column(String, nullable=True)
    linkedin_post_id = Column(String, nullable=True)

    email = relationship("Email", back_populates="linkedin_posts")
    slogan = relationship("Slogan")
    image = relationship("Image", backref="linkedin_posts", lazy="joined")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    username = Column(String, unique=True, nullable=True, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class OAuthCredential(Base):
    __tablename__ = "oauth_credentials"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(20), nullable=False)
    encrypted_token = Column(Text, nullable=False)


class OAuthState(Base):
    __tablename__ = "oauth_states"
    state_hash = Column(String(64), primary_key=True)
    browser_hash = Column(String(64), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(20), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)
