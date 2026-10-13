"""Hugging Face text-to-image client with private, generated artifact storage."""

import io
import os
import re
import uuid
from pathlib import Path

import requests
from PIL import Image


class ImageGenerationError(RuntimeError):
    """A sanitized provider or image-validation failure."""


class HuggingFaceImageGenerationTool:
    def __init__(self, api_key, output_dir, model):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", model):
            raise ValueError("HUGGINGFACE_MODEL must be an owner/model identifier.")
        self.output_dir = Path(output_dir)
        self.api_url = f"https://router.huggingface.co/hf-inference/models/{model}"
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.http = requests.Session()
        self.http.trust_env = False

    def generate_image(self, description):
        """Return a private PNG basename after a successful provider response."""
        path = None
        try:
            response = self.http.post(
                self.api_url,
                headers=self.headers,
                json={"inputs": description},
                timeout=(5, 60),
                allow_redirects=False,
            )
            if response.status_code != 200 or len(response.content) > 10 * 1024 * 1024:
                raise ImageGenerationError("Image provider did not return a valid image response.")
            with Image.open(io.BytesIO(response.content)) as image:
                image.load()
                self.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                if self.output_dir.is_symlink():
                    raise ImageGenerationError("Invalid generated image directory.")
                path = self.output_dir / f"generated_{uuid.uuid4().hex}.png"
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as output:
                    image.save(output, format="PNG")
                if path.stat().st_size > 10 * 1024 * 1024:
                    raise ImageGenerationError("Generated image exceeds the upload limit.")
                return path.name
        except Exception:
            if path is not None:
                path.unlink(missing_ok=True)
            raise ImageGenerationError(
                "Image generation failed; no complete draft was created."
            ) from None
