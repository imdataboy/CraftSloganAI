# CraftSloganAI

CraftSloganAI is a multi-agent AI application that automates marketing content creation from product descriptions or Gmail messages. Powered by five CrewAI agents, it generates slogans, visuals, and LinkedIn post drafts, with a human review process for publishing and scheduling.

## Features

- **AI Content Generation:** Generate marketing slogans, images, and LinkedIn posts.
- **Multi-Agent Workflow:** Coordinate five specialized agents using CrewAI.
- **Gmail Integration:** Generate content from incoming email messages.
- **LinkedIn Automation:** Review, approve, publish, or schedule posts.
- **AI Assistant:** Gemini-powered CraftBot for conversational assistance.

## Tech Stack

**Backend:** Python 3.12, Flask, CrewAI, SQLAlchemy, PostgreSQL

**Frontend:** HTML, CSS, JavaScript

**AI & Integrations:** Groq, Hugging Face, Gemini, Gmail API, LinkedIn API, Google Calendar API

## Installation & Usage

### 1. Clone the repository

```bash
git clone https://github.com/PandaLakes/Craftslogan_AI.git
cd Craftslogan_AI
```

### 2. Install dependencies

Requires Python 3.12 and Docker with Compose.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and configure the required API credentials, database connection, and application secrets.

Generate a JWT secret and a Fernet encryption key using Python:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set the generated values as `JWT_SECRET_KEY` and `TOKEN_ENCRYPTION_KEY` in `.env`.

For Gmail and LinkedIn OAuth, register these callback URLs with the respective providers, where supported:

```text
http://127.0.0.1:5000/auth/gmail/callback
http://127.0.0.1:5000/auth/linkedin/callback
```

### 4. Initialize the database

For a new, empty database:

```bash
docker compose up -d postgres
python -m slogancraftai.initialize_db
```

For an existing database, back it up and follow the Alembic migration instructions instead.

### 5. Run the application

Start the Flask backend:

```bash
python -m slogancraftai.main
```

In a second terminal, from the repository root, start the frontend:

```bash
.venv/bin/python -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

Open **http://127.0.0.1:5500/index.html** in your browser.

### 6. Generate content

1. Create an account and sign in.
2. Enter a product description or connect Gmail to retrieve an email.
3. Generate marketing content using the AI agents.
4. Review the slogan, image, and LinkedIn draft.
5. Approve, publish, or schedule the post.

LinkedIn publishing requires an authorized LinkedIn account. Scheduling requires Google Calendar integration and a running backend.

## Demo

[Watch the video demonstration](VIDEO_URL)
