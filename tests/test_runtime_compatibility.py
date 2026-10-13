"""Construct the existing five-agent crew without executing any providers."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_installed_crewai_constructs_existing_agents_offline(tmp_path):
    if importlib.util.find_spec("crewai") is None:
        pytest.skip("Install requirements.txt to run the real CrewAI compatibility check.")
    env = dict(
        os.environ,
        PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
        XDG_DATA_HOME=str(tmp_path / "data"),
        OTEL_SDK_DISABLED="true",
        CREWAI_TELEMETRY_OPT_OUT="true",
        LITELLM_LOCAL_MODEL_COST_MAP="True",
        MODEL="groq/synthetic-test-model",
        GROQ_API_KEY="synthetic-offline-test",
        HUGGINGFACE_API_KEY="synthetic-offline-test",
        HUGGINGFACE_MODEL="synthetic/model",
    )
    code = r"""
import socket, urllib.request

def blocked(*args, **kwargs):
    raise RuntimeError('Network disabled for compatibility check')
socket.socket.connect = blocked
socket.create_connection = blocked
urllib.request.urlopen = blocked
import requests
requests.sessions.Session.request = blocked
import base64
from pathlib import Path
from slogancraftai.settings import Settings
from slogancraftai.crew import Slogancraftai
settings = Settings('sqlite://', 'synthetic-test-only-'*4,
    base64.urlsafe_b64encode(b'0'*32).decode(), ('http://127.0.0.1:5500',),
    'http://127.0.0.1:5500', 'http://127.0.0.1:5000', Path('generated'))
crew = Slogancraftai(settings, None, 1, None)
crew.initialize_agents()
crew.initialize_tasks()
result = crew.crew()
assert len(result.agents) == len(result.tasks) == 5
assert len(result.agents[3].tools) == 1
assert result.agents[3].tools[0].args_schema.model_fields['description']
assert result.agents[4].tools == []
# Execute the real CrewAI orchestration with deterministic fake model responses.
import io
from unittest.mock import Mock, patch
from PIL import Image
from slogancraftai.db import Base, create_session_factory
from slogancraftai.models import LinkedInPost, User
factory, engine = create_session_factory('sqlite:///workflow.sqlite3')
Base.metadata.create_all(engine)
with factory.begin() as db:
    db.add(User(full_name='Synthetic User', email='synthetic@example.invalid',
                username='synthetic', password_hash='synthetic-unusable-hash'))
workflow = Slogancraftai(settings, factory, 1, None)
image = io.BytesIO()
Image.new('RGB', (2, 2)).save(image, 'PNG')
workflow.huggingface_tool.http = Mock()
workflow.huggingface_tool.http.post.return_value = Mock(status_code=200, content=image.getvalue())
outputs = [
    'Final Answer: Synthetic email summary',
    'Final Answer: Synthetic slogan',
    'Final Answer: A synthetic product image',
    'Thought: Generate the image.\nAction: generate_marketing_image\nAction Input: {"description": "A synthetic product image"}',
    'Final Answer: Synthetic LinkedIn draft #Synthetic',
]
with patch('crewai.LLM.call', side_effect=outputs) as model:
    response = workflow.kickoff(manual_email={'subject': 'Synthetic', 'body': 'Synthetic announcement'})
    assert model.call_count == 5
with factory() as db:
    post = db.get(LinkedInPost, response['post_id'])
    assert post.post_text == 'Synthetic LinkedIn draft #Synthetic'
    assert post.post_status == 'Draft' and post.status == 'Pending'
    assert post.image.is_generated and post.user_id == 1
workflow.huggingface_tool.http.post.assert_called_once()
engine.dispose()
print('Offline construction passed')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "Offline construction passed" in result.stdout


def test_installed_console_entry_points_resolve():
    from importlib.metadata import distribution

    from slogancraftai.main import serve

    entries = {
        entry.name: entry
        for entry in distribution("slogancraftai").entry_points
        if entry.group == "console_scripts"
    }
    assert set(entries) == {"slogancraftai", "run_crew"}
    assert all(entry.load() is serve for entry in entries.values())


def test_database_initialization_module_in_fresh_process(tmp_path):
    import base64
    import sqlite3

    database = tmp_path / "empty.sqlite3"
    env = dict(
        os.environ,
        DATABASE_URL=f"sqlite:///{database}",
        JWT_SECRET_KEY="synthetic-startup-test-key-" * 3,
        TOKEN_ENCRYPTION_KEY=base64.urlsafe_b64encode(b"0" * 32).decode(),
        FRONTEND_ORIGINS="http://127.0.0.1:5500",
        FRONTEND_URL="http://127.0.0.1:5500",
        BACKEND_URL="http://127.0.0.1:5000",
    )
    result = subprocess.run(
        [sys.executable, "-m", "slogancraftai.initialize_db"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {
            "users",
            "emails",
            "slogans",
            "images",
            "linkedin_posts",
            "oauth_credentials",
            "oauth_states",
        } <= tables
        assert (
            db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "p0_security_20261013"
        )
