# Ariadne

A local-first, voice-first engineering thought partner for coding-agent workflows.

Call your workstation, talk through a codebase problem, let Ariadne inspect your repo read-only, and leave with a structured implementation brief for Codex, Claude Code, or another coding agent.

## Current Status

Early private beta. Ariadne is intended for one engineer running the tool locally against a personal, open-source, or explicitly authorized repo.

## Requirements

- macOS or Linux
- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- [OpenAI Codex CLI](https://github.com/openai/codex) authenticated locally
- [ngrok](https://ngrok.com/download) authenticated locally
- API keys: OpenAI, Daily, Deepgram, Cartesia

## Setup

Run once from the repo root:

```bash
./setup.sh
```

The script asks for your name, project name, the repo Ariadne should inspect, and your API keys. It configures everything and optionally generates a project background for the repo.

## Start Ariadne

```bash
./start_ariadne.sh
```

This starts an ngrok tunnel, registers it with your Daily phone number, and launches the bot. When it prints your phone number, call it.

Try saying:

```
I want to think through a change in this repo. Can you help me investigate where to start?
```

Press **Ctrl-C** to stop. ngrok is cleaned up automatically.

## Core Workflow

1. `./setup.sh` — one-time configuration
2. `./start_ariadne.sh` — start a session
3. Call your Daily number
4. Talk through an engineering problem
5. Ask Ariadne to investigate the repo
6. Ask Ariadne to write an implementation brief
7. Find the brief in `<repo>/.ariadne/briefs/` and hand it to a coding agent

## What Lives Where

**On your machine** (`~/.ariadne/`):

| Artifact | Path |
|---|---|
| Session logs and timelines | `~/.ariadne/logs/session-logs/<session-id>/` |
| Call transcripts | `~/.ariadne/logs/session-logs/<session-id>/transcript.md` |
| Project background cache | `~/.ariadne/project-backgrounds/<repo-name>-<hash>/PROJECT_BACKGROUND.md` |

**In the inspected repo** (`<repo>/.ariadne/`):

| Artifact | Path |
|---|---|
| Implementation briefs | `<repo>/.ariadne/briefs/ariadne-*.md` |

Setup will offer to add `.ariadne/` to the target repo's `.gitignore`.

## Privacy and Safety

Read [PRIVACY.md](PRIVACY.md) before using Ariadne on any non-public repo.

Short version: logs, transcripts, and briefs are local by default. Voice audio, transcription, LLM turns, TTS, and repo findings go to your configured cloud providers. Do not use Ariadne with employer-owned or confidential repos unless authorized.

---

## Using Implementation Briefs

Ariadne writes briefs to `<ARIADNE_REPO_PATH>/.ariadne/briefs/`. Hand one to a coding agent:

```bash
cat /path/to/repo/.ariadne/briefs/ariadne-<title>-<timestamp>.md | codex
```

## Refreshing Project Background

Project background gives Ariadne lightweight orientation to the repo before a call. Refresh it when the repo changes significantly:

```bash
ARIADNE_REPO_PATH=/path/to/repo ./tools/refresh_project_background.sh
```

Output goes to `~/.ariadne/project-backgrounds/<repo-name>-<hash>/PROJECT_BACKGROUND.md` and is picked up automatically via `ARIADNE_PROJECT_BACKGROUND_PATH` in `bot/.env`.

---

## Advanced

### Running without start_ariadne.sh

```bash
# Terminal 1 — tunnel
ngrok http 7860

# Terminal 2 — register webhook
./tools/register-dialin.sh https://<your-ngrok-url>/daily-dialin-webhook

# Terminal 3 — bot
cd bot && uv run bot.py -t daily --dialin
```

### Other run modes

From `bot/`:

| Mode | Command |
|---|---|
| Daily WebRTC browser | `uv run bot.py -t daily` |
| SmallWebRTC local browser | `uv run bot.py` |

### Docker

Copy and fill in the root env file:

```bash
cp .env.example .env
# Set ARIADNE_REPO_HOST_PATH, ARIADNE_BRIEFS_HOST_PATH, LOGS_HOST_PATH
```

Run:

```bash
docker compose up --build
```

Bot runner: `http://localhost:7860` — Debug server (if enabled): `http://localhost:8765/debug/sessions`

### Manual setup

If you prefer not to use `./setup.sh`:

```bash
cd bot
uv sync
cp .env.example .env
# Fill in API keys and paths
```

See `bot/.env.example` for all variables.

---

## Troubleshooting

**`start_ariadne.sh` exits: ngrok tunnel did not appear**
Make sure ngrok is authenticated: `ngrok config add-authtoken <your-token>`

**No repo investigation results**
Check that `ARIADNE_REPO_PATH` points to an existing directory and that `codex` is installed and authenticated: `codex --version`

**Briefs not appearing**
Check `ARIADNE_REPO_PATH` in `bot/.env`. Briefs default to `<ARIADNE_REPO_PATH>/.ariadne/briefs/`.

**Call hangs up too quickly**
Increase `ARIADNE_IDLE_TIMEOUT_SECONDS` in `bot/.env`.

**Debug server**
Set `ARIADNE_DEBUG_SERVER_ENABLED=true` in `bot/.env`, then open `http://localhost:8765/debug/sessions`.

---

## Project Structure

```text
ariadne/
├── setup.sh                  # One-time setup
├── start_ariadne.sh           # Start a session (ngrok + Daily + bot)
├── bot/
│   ├── bot.py
│   ├── ariadne/
│   │   ├── pipeline.py
│   │   ├── agent.py
│   │   ├── tools.py
│   │   ├── task_queue.py
│   │   ├── orchestrator.py
│   │   ├── repo_investigator.py
│   │   ├── implementation_doc.py
│   │   ├── paths.py
│   │   ├── session.py
│   │   ├── session_logger.py
│   │   ├── transport.py
│   │   ├── stt.py
│   │   ├── tts.py
│   │   ├── debug_server.py
│   │   └── idle_timeout.py
│   ├── pyproject.toml
│   ├── .env.example
│   └── Dockerfile
├── tools/
│   ├── register-dialin.sh
│   ├── refresh_project_background.sh
│   └── build-deploy.sh
├── docs/
├── docker-compose.yml
├── .env.example
├── PRIVACY.md
└── README.md
```

