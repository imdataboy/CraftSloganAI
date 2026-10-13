"""Regression checks for MIME parsing and image generation; no provider calls."""

import base64
import io
import stat
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from PIL import Image

from slogancraftai.security import SecurityError
from slogancraftai.tools.image_generator import HuggingFaceImageGenerationTool, ImageGenerationError
from slogancraftai.tools.read_mail import GmailTool


def encoded(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def mail_client(context, messages):
    tool = GmailTool(context[2])
    tool.email_service = Mock()
    api = tool.email_service.users.return_value.messages.return_value
    api.list.return_value.execute.return_value = {
        "messages": [{"id": str(i)} for i in range(len(messages))]
    }
    api.get.return_value.execute.side_effect = messages
    return tool


def test_nested_gmail_body_and_headers(context):
    tool = mail_client(
        context,
        [
            {
                "internalDate": "2",
                "payload": {
                    "headers": [
                        {"name": "subject", "value": "Slogan"},
                        {"name": "From", "value": "synthetic@example.invalid"},
                    ],
                    "parts": [
                        {
                            "mimeType": "multipart/alternative",
                            "parts": [
                                {"mimeType": "text/html", "body": {"data": encoded("<p>HTML</p>")}},
                                {
                                    "mimeType": "text/plain",
                                    "body": {"data": encoded("Synthetic text ✓")},
                                },
                            ],
                        }
                    ],
                },
            }
        ],
    )
    assert tool.get_latest_email() == {
        "subject": "Slogan",
        "sender": "synthetic@example.invalid",
        "body": "Synthetic text ✓",
    }


def test_latest_email_does_not_reuse_previous_body(context):
    tool = mail_client(
        context,
        [
            {
                "internalDate": "1",
                "payload": {"mimeType": "text/plain", "body": {"data": encoded("Older")}},
            },
            {
                "internalDate": "2",
                "payload": {"mimeType": "text/html", "body": {"data": encoded("<p>Latest</p>")}},
            },
        ],
    )
    with pytest.raises(SecurityError, match="no readable plain-text"):
        tool.get_latest_email()


def test_no_matching_gmail_returns_none(context):
    assert mail_client(context, []).get_latest_email() is None


def test_gmail_attachment_is_not_message_body():
    assert (
        GmailTool._plain_text(
            {
                "filename": "private.txt",
                "mimeType": "text/plain",
                "body": {"data": encoded("attachment")},
            }
        )
        is None
    )


def image_client(tmp_path):
    tool = HuggingFaceImageGenerationTool("synthetic-key", tmp_path / "1", "synthetic/model")
    tool.http = Mock()
    return tool


def test_image_provider_saves_valid_private_png(tmp_path):
    tool = image_client(tmp_path)
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buffer, "PNG")
    tool.http.post.return_value = SimpleNamespace(status_code=200, content=buffer.getvalue())
    filename = tool.generate_image("Synthetic image description")
    path = tool.output_dir / filename
    assert filename.startswith("generated_") and filename.endswith(".png")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with Image.open(path) as result:
        assert result.format == "PNG"
    call = tool.http.post.call_args
    assert call.args[0] == "https://router.huggingface.co/hf-inference/models/synthetic/model"
    assert call.kwargs["json"] == {"inputs": "Synthetic image description"}
    assert call.kwargs["timeout"] == (5, 60) and not call.kwargs["allow_redirects"]


@pytest.mark.parametrize("failure", [401, 429, 500, "invalid_image", "timeout", "connection"])
def test_image_provider_failures_leave_no_artifact(tmp_path, failure):
    tool = image_client(tmp_path)
    if failure in ("timeout", "connection"):
        tool.http.post.side_effect = (
            requests.Timeout("synthetic-private")
            if failure == "timeout"
            else requests.ConnectionError("synthetic-private")
        )
    else:
        tool.http.post.return_value = SimpleNamespace(
            status_code=200 if failure == "invalid_image" else failure, content=b"synthetic-private"
        )
    with pytest.raises(ImageGenerationError) as error:
        tool.generate_image("Synthetic prompt")
    assert "synthetic-private" not in str(error.value)
    assert not list(tmp_path.rglob("*.png"))
