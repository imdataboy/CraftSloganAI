"""Durable claims prevent duplicate application submissions, including retries."""

from datetime import datetime, timezone

from sqlalchemy import update

from .models import LinkedInPost
from .security import SecurityError, generated_image_bytes
from .tools.linkedin_poster import LinkedInError


class PostConflict(ValueError):
    pass


def publish_post(factory, settings, user_id, post_id, client_factory):
    with factory() as db:
        post = db.query(LinkedInPost).filter_by(id=post_id, user_id=user_id).first()
        if post is None:
            raise LookupError("Post not found.")
        if post.status != "Approved" or post.post_status not in ("Draft", "Scheduled"):
            raise PostConflict("Post is not approved or has already been attempted.")
        image_bytes = (
            generated_image_bytes(post.image, user_id, settings)
            if post.image_id is not None
            else None
        )
        text = post.post_text
        claimed = db.execute(
            update(LinkedInPost)
            .where(
                LinkedInPost.id == post_id,
                LinkedInPost.user_id == user_id,
                LinkedInPost.status == "Approved",
                LinkedInPost.post_status.in_(["Draft", "Scheduled"]),
            )
            .values(post_status="Publishing")
        ).rowcount
        db.commit()  # Persist the claim BEFORE contacting LinkedIn.
        if claimed != 1:
            raise PostConflict("Publication is already in progress or has been attempted.")
    try:
        result = client_factory(user_id).post_to_linkedin(text, image_bytes)
        if not isinstance(result, dict) or not result.get("id"):
            raise LinkedInError("publication confirmation", uncertain=True)
    except (LinkedInError, SecurityError) as exc:
        failed_status = "PublicationUnknown" if getattr(exc, "uncertain", False) else "Failed"
        with factory.begin() as db:
            db.execute(
                update(LinkedInPost)
                .where(
                    LinkedInPost.id == post_id,
                    LinkedInPost.user_id == user_id,
                    LinkedInPost.post_status == "Publishing",
                )
                .values(post_status=failed_status)
            )
        raise
    except Exception:
        # Unknown failures may occur after a remote side effect. Never retry automatically.
        with factory.begin() as db:
            db.execute(
                update(LinkedInPost)
                .where(
                    LinkedInPost.id == post_id,
                    LinkedInPost.user_id == user_id,
                    LinkedInPost.post_status == "Publishing",
                )
                .values(post_status="PublicationUnknown")
            )
        raise LinkedInError("publication", uncertain=True) from None
    with factory.begin() as db:
        db.execute(
            update(LinkedInPost)
            .where(
                LinkedInPost.id == post_id,
                LinkedInPost.user_id == user_id,
                LinkedInPost.post_status == "Publishing",
            )
            .values(
                post_status="Published",
                linkedin_post_id=result["id"],
                posted_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
    return result
