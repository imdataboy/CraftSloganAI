"""Exercise the real workflow persistence with fake LLM/image/Gmail providers."""

import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image as PILImage
from pydantic import BaseModel

from slogancraftai.models import LinkedInPost, Slogan
from slogancraftai.security import SecurityError


@pytest.fixture
def owned_crew(context, monkeypatch):
    fake_crewai = ModuleType("crewai")
    fake_crewai.Agent = lambda **kwargs: SimpleNamespace(**kwargs)
    fake_crewai.LLM = lambda **kwargs: SimpleNamespace(**kwargs)
    fake_crewai.Task = lambda **kwargs: SimpleNamespace(output=None, **kwargs)
    fake_crewai.Process = SimpleNamespace(sequential="sequential")

    class FakeCrew:
        def __init__(self, **kwargs):
            self.tasks = kwargs["tasks"]

        def kickoff(self):
            outputs = [
                "Email summary",
                "Synthetic slogan",
                "Image description",
                "Image generated",
                "LinkedIn post with #Synthetic",
            ]
            for index, task in enumerate(self.tasks):
                if index == 3:
                    task.agent.tools[0].run(description=outputs[2])
                task.output = SimpleNamespace(raw=outputs[index])

    fake_crewai.Crew = FakeCrew
    fake_tools = ModuleType("crewai.tools")

    class FakeBaseTool(BaseModel):
        def run(self, **kwargs):
            return self._run(**kwargs)

    fake_tools.BaseTool = FakeBaseTool
    monkeypatch.setitem(sys.modules, "crewai.tools", fake_tools)
    monkeypatch.delitem(sys.modules, "slogancraftai.tools.image_tool", raising=False)
    monkeypatch.setitem(sys.modules, "crewai", fake_crewai)
    # Reimport using fake external library only; exercise project methods unchanged.
    monkeypatch.delitem(sys.modules, "slogancraftai.crew", raising=False)
    module = importlib.import_module("slogancraftai.crew")
    monkeypatch.setenv("MODEL", "synthetic-model")
    monkeypatch.setenv("HUGGINGFACE_MODEL", "synthetic/model")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-provider-value")
    monkeypatch.setenv("HUGGINGFACE_API_KEY", "synthetic-provider-value")
    _, factory, settings = context
    gmail = Mock()
    crew = module.Slogancraftai(settings, factory, 1, gmail)
    yield crew
    monkeypatch.delitem(sys.modules, "slogancraftai.crew", raising=False)


def test_real_workflow_saves_authenticated_ownership(context, owned_crew):
    crew = owned_crew
    _, factory, settings = context

    def generate(description):
        folder = settings.generated_image_dir / "1"
        folder.mkdir(parents=True)
        name = "generated_" + "b" * 32 + ".png"
        PILImage.new("RGB", (2, 2)).save(folder / name)
        return name

    crew.huggingface_tool.generate_image = generate
    result = crew.kickoff(
        manual_email={
            "subject": "Synthetic email",
            "body": "Synthetic product",
            "sender": "synthetic",
        }
    )
    crew.gmail_tool.authenticate_gmail.assert_not_called()
    assert len(crew.agents) == len(crew.tasks) == 5
    assert result["status"] == "Pending"
    with factory() as db:
        post = db.get(LinkedInPost, result["post_id"])
        assert post.user_id == post.email.user_id == post.slogan.user_id == post.image.user_id == 1
        assert post.status == "Pending" and post.post_status == "Draft"
        assert post.image.is_generated and len(post.image.sha256) == 64
        assert post.post_text == "LinkedIn post with #Synthetic"
        assert post.slogan.slogan_text == "Synthetic slogan"
        assert crew.tasks[1].context == [crew.tasks[0]]
        assert crew.tasks[3].context == [crew.tasks[2]]
        assert not crew.agents[4].tools


@pytest.mark.parametrize("operation", ["slogan", "image", "post"])
def test_persistence_helpers_cannot_bypass_ownership_or_confirmation(owned_crew, operation):
    with pytest.raises(SecurityError):
        if operation == "slogan":
            owned_crew.save_slogan_to_db(2, "Synthetic")
        elif operation == "image":
            owned_crew.save_image_to_db(2, "Synthetic", "../private.png")
        elif operation == "post":
            owned_crew.save_draft_post_to_db(2, None, None, "Synthetic")


def test_draft_cannot_link_another_users_slogan(context, owned_crew):
    with context[1].begin() as db:
        slogan = Slogan(user_id=2, email_id=2, slogan_text="Private synthetic text")
        db.add(slogan)
        db.flush()
        identifier = slogan.id
    with pytest.raises(SecurityError):
        owned_crew.save_draft_post_to_db(1, identifier, None, "Synthetic")


@pytest.mark.parametrize("path", ["../private.png", "/etc/passwd"])
def test_image_registration_rejects_paths_before_reading(owned_crew, path):
    with pytest.raises(SecurityError):
        owned_crew.save_image_to_db(1, "Synthetic", path)


def test_invented_image_output_does_not_create_a_draft(context, owned_crew, monkeypatch):
    # A text response claiming an image exists is insufficient without the tool artifact.
    import slogancraftai.crew as module

    monkeypatch.setattr(
        module.GenerateMarketingImage, "_run", lambda *args, **kwargs: "invented.png"
    )
    with pytest.raises(RuntimeError, match="did not generate an image"):
        owned_crew.kickoff(manual_email={"subject": "Synthetic", "body": "Synthetic"})
    with context[1]() as db:
        assert db.query(LinkedInPost).count() == 3


def test_image_tool_only_attempts_generation_once(owned_crew):
    owned_crew.initialize_agents()
    generator = Mock(return_value="generated_" + "b" * 32 + ".png")
    owned_crew.huggingface_tool.generate_image = generator
    first = owned_crew.image_tool.run(description="Synthetic description")
    assert owned_crew.image_tool.run(description="Repeated request") == first
    generator.assert_called_once_with("Synthetic description")


def test_missing_agent_text_fails_before_draft_persistence(context, owned_crew, monkeypatch):
    # Do not store a partial/hallucinated draft when an agent returns no text.
    def missing_text(task):
        raise RuntimeError("Missing output")

    monkeypatch.setattr(owned_crew, "_task_text", missing_text)
    owned_crew.huggingface_tool.generate_image = Mock(return_value="generated_" + "b" * 32 + ".png")
    with pytest.raises(RuntimeError, match="Missing output"):
        owned_crew.kickoff(manual_email={"subject": "Synthetic", "body": "Synthetic"})
    with context[1]() as db:
        assert db.query(LinkedInPost).count() == 3
