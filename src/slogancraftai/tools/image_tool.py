"""CrewAI adapter for the image generator; filesystem paths are never tool inputs."""

import json

from crewai.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from .image_generator import HuggingFaceImageGenerationTool


class ImagePrompt(BaseModel):
    description: str = Field(
        min_length=1, max_length=20000, description="Image_Creator's image description"
    )


class GenerateMarketingImage(BaseTool):
    name: str = "generate_marketing_image"
    description: str = "Generate the marketing PNG from the image description. Returns its private artifact filename."
    args_schema: type[BaseModel] = ImagePrompt
    result_as_answer: bool = True
    _generator: HuggingFaceImageGenerationTool = PrivateAttr()
    _attempted: bool = PrivateAttr(default=False)
    _filename: str | None = PrivateAttr(default=None)
    _description: str | None = PrivateAttr(default=None)

    def __init__(self, generator):
        super().__init__()
        self._generator = generator

    @property
    def filename(self):
        return self._filename

    @property
    def image_description(self):
        return self._description

    def _run(self, description: str) -> str:
        # One provider attempt per workflow, even if an agent repeats a tool call.
        if not self._attempted:
            self._attempted = True
            self._description = ImagePrompt(description=description).description
            self._filename = self._generator.generate_image(self._description)
        if not self._filename:
            raise RuntimeError("Image generation did not produce an artifact.")
        return json.dumps({"image_filename": self._filename})
