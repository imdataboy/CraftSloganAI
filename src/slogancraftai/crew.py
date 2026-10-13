import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml
from crewai import LLM, Agent, Crew, Process, Task

from .models import Email, Image, LinkedInPost, Slogan
from .security import SecurityError, generated_image_bytes
from .tools.image_generator import HuggingFaceImageGenerationTool
from .tools.image_tool import GenerateMarketingImage


class Slogancraftai:
    """Run the five marketing agents and persist an owned draft for review."""

    agents_config_file = Path(__file__).parent / "config/agents.yaml"
    tasks_config_file = Path(__file__).parent / "config/tasks.yaml"

    def __init__(self, settings, session_factory, user_id, gmail_tool):
        self.settings = settings
        self.session_factory = session_factory
        self.user_id = user_id
        self.llm = LLM(
            model=settings.provider_value("MODEL"), api_key=settings.provider_value("GROQ_API_KEY")
        )
        self.gmail_tool = gmail_tool
        self.huggingface_tool = HuggingFaceImageGenerationTool(
            api_key=settings.provider_value("HUGGINGFACE_API_KEY"),
            output_dir=settings.generated_image_dir / str(user_id),
            model=settings.provider_value("HUGGINGFACE_MODEL"),
        )
        self.latest_email = None
        self.agents = []
        self.tasks = []

        # Load configurations
        with open(self.agents_config_file, "r") as file:
            self.agents_config = yaml.safe_load(file)

        with open(self.tasks_config_file, "r") as file:
            self.tasks_config = yaml.safe_load(file)

    def _owned_record(self, db, model, identifier):
        record = db.query(model).filter_by(id=identifier, user_id=self.user_id).first()
        if record is None:
            raise SecurityError("Related records must belong to the authenticated user.")
        return record

    def _owned_post_records(self, db, email_id, slogan_id, image_id):
        self._owned_record(db, Email, email_id)
        for model, identifier in ((Slogan, slogan_id), (Image, image_id)):
            if identifier is not None:
                record = self._owned_record(db, model, identifier)
                if record.email_id != email_id:
                    raise SecurityError("Related records must belong to the same email.")

    def save_slogan_to_db(self, email_id, slogan_text):
        with self.session_factory() as db:
            self._owned_record(db, Email, email_id)
            slogan = Slogan(
                user_id=self.user_id,
                email_id=email_id,
                slogan_text=slogan_text,
                created_at=datetime.now(timezone.utc),
            )
            db.add(slogan)
            db.commit()
            db.refresh(slogan)
            return slogan

    def save_email_to_db(self, email_data):
        """Save email details to the database."""
        with self.session_factory() as db:
            email = Email(
                user_id=self.user_id,
                email_subject=email_data["subject"],
                email_body=email_data["body"],
                sender=email_data.get("sender"),
                received_at=datetime.now(timezone.utc),
            )
            db.add(email)
            db.commit()
            db.refresh(email)
            return email

    def save_image_to_db(self, email_id, description, image_path):
        """Save image details to the database."""
        with self.session_factory() as db:
            self._owned_record(db, Email, email_id)
            folder = self.settings.generated_image_dir / str(self.user_id)
            if not isinstance(image_path, str) or not re.fullmatch(
                r"generated_[0-9a-f]{32}\.png", image_path
            ):
                raise SecurityError("Invalid generated image path.")
            path = folder / image_path
            if (
                folder.is_symlink()
                or path.is_symlink()
                or not path.is_file()
                or path.stat().st_size > 10 * 1024 * 1024
            ):
                raise SecurityError("Invalid generated image path.")
            image = Image(
                user_id=self.user_id,
                email_id=email_id,
                description=description,
                image_path=image_path,
                is_generated=True,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                created_at=datetime.now(timezone.utc),
            )
            generated_image_bytes(image, self.user_id, self.settings)
            db.add(image)
            db.commit()
            db.refresh(image)
            return image

    def save_draft_post_to_db(self, email_id, slogan_id, image_id, post_text):
        """Save the draft post with Pending status."""
        with self.session_factory() as db:
            self._owned_post_records(db, email_id, slogan_id, image_id)
            post = LinkedInPost(
                user_id=self.user_id,
                email_id=email_id,
                slogan_id=slogan_id,
                image_id=image_id,
                post_text=post_text,
                status="Pending",  # Set status to Pending
                post_status="Draft",
            )
            db.add(post)
            db.commit()
            db.refresh(post)
            return post

    def fetch_email_content(self, manual_email=None):
        """Save manual input or the latest matching email under this user's owner ID."""
        if manual_email is None:
            self.gmail_tool.authenticate_gmail()
            manual_email = self.gmail_tool.get_latest_email()
        self.latest_email = self.save_email_to_db(manual_email) if manual_email else None

    def initialize_agents(self):
        """Only Image_Generator receives a tool; publication stays outside the crew."""
        self.image_tool = GenerateMarketingImage(self.huggingface_tool)
        roles = ("Mail_Reader", "Slogan_Maker", "Image_Creator", "Image_Generator", "Poster")
        self.agents = [
            Agent(
                config=self.agents_config[role],
                llm=self.llm,
                allow_delegation=False,
                verbose=False,
                tools=[self.image_tool] if role == "Image_Generator" else [],
            )
            for role in roles
        ]

    def initialize_tasks(self):
        email_content = (
            self.latest_email.email_body if self.latest_email else "No content available."
        )

        email_reading_task = Task(
            config=self.tasks_config["email_reading_task"],
            description=(
                f"Analyze the provided email content to identify and extract key information regarding "
                f"product launches, company updates, or any other significant announcements. "
                f"Summarize the main points of the email concisely.\n\nEmail content:\n{email_content}"
            ),
            agent=self.agents[0],
        )
        slogan_generation_task = Task(
            config=self.tasks_config["slogan_generation_task"],
            agent=self.agents[1],
            context=[email_reading_task],
        )
        image_description_task = Task(
            config=self.tasks_config["image_description_task"],
            agent=self.agents[2],
            context=[email_reading_task, slogan_generation_task],
        )
        image_generation_task = Task(
            config=self.tasks_config["image_generation_task"],
            agent=self.agents[3],
            context=[image_description_task],
        )
        social_media_posting_task = Task(
            config=self.tasks_config["social_media_posting_task"],
            agent=self.agents[4],
            context=[email_reading_task, slogan_generation_task, image_generation_task],
        )

        self.tasks = [
            email_reading_task,
            slogan_generation_task,
            image_description_task,
            image_generation_task,
            social_media_posting_task,
        ]

    def crew(self):
        """Creates the SloganCraftAI crew"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
        )

    @staticmethod
    def _task_text(task):
        text = getattr(task.output, "raw", None)
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("An agent did not produce the required text output.")
        return text.strip()

    def kickoff(self, manual_email=None):
        """Generate a draft; only the authenticated publishing service may publish it."""
        self.fetch_email_content(manual_email)
        if self.latest_email is None:
            return {"error": "No email available"}

        self.initialize_agents()
        self.initialize_tasks()
        self.crew().kickoff()

        slogan_text = self._task_text(self.tasks[1])
        self._task_text(self.tasks[2])
        post_text = self._task_text(self.tasks[4])
        # Trust the tool's actual artifact, never a filename invented in model output.
        if not self.image_tool.filename:
            raise RuntimeError("The image agent did not generate an image.")
        slogan = self.save_slogan_to_db(self.latest_email.id, slogan_text)
        image = self.save_image_to_db(
            self.latest_email.id, self.image_tool.image_description, self.image_tool.filename
        )
        draft = self.save_draft_post_to_db(self.latest_email.id, slogan.id, image.id, post_text)
        return {"post_id": draft.id, "slogan": slogan_text, "status": "Pending"}
