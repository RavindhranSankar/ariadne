# Ariadne

> **Early beta.** Ariadne is under active development. Expect rough edges, breaking changes between versions, and incomplete documentation. It is intended for personal use against repos you own or have explicit authorization to inspect.

A local-first, voice-first engineering thought partner for coding-agent workflows.

Call your workstation, talk through a codebase problem, let Ariadne inspect your repo read-only, and leave with a structured implementation brief for Codex, Claude Code, or another coding agent.

---

## Call Ariadne

The fastest way to understand Ariadne is to call it.

**+1 (209) 821-5967**

This instance is pointed at the Ariadne repo itself. It can read its own source to answer you.

Some things worth trying:

```
How do you actually work?
```

```
Why can't you just edit the code yourself?
```

```
What happens between when I ask you to investigate something and when you report back?
```

```
Investigate yourself — what's the most interesting design decision in your own codebase?
```

```
Walk me through how an implementation brief gets written.
```

```
Write me a brief for adding a new capability to yourself.
```

That last one runs the full workflow: live repo investigation, then a structured handoff doc — written about Ariadne, by Ariadne.

That's what you'd set up on your own repo.

---

## Requirements

- macOS or Linux
- Python 3.11+
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
├── setup.sh                       # One-time setup
├── start_ariadne.sh                # Start a session (ngrok + Daily + bot)
├── bot/
│   ├── bot.py                     # Entry point
│   ├── ariadne/
│   │   ├── runner.py              # Composition root; Pipecat pipeline wiring
│   │   ├── config.py              # AriadneConfig; centralised env var parsing
│   │   ├── ariadne_session.py     # AriadneSession; turn and investigation counters
│   │   ├── ariadne_task_queue.py  # AriadneTaskQueue, AriadneTask, TaskKind, TaskStatus
│   │   ├── task_result.py         # TaskResult, TaskArtifact typed domain objects
│   │   ├── task_handler.py        # TaskHandler protocol
│   │   ├── task_executor.py       # TaskExecutor; maps TaskKind to handlers
│   │   ├── orchestrator.py        # Orchestrator; task lifecycle only
│   │   ├── session_logger.py      # SessionLogger; JSONL + transcript + SSE
│   │   ├── idle_timeout.py        # IdleTimeout watchdog
│   │   ├── transport.py           # Daily / SmallWebRTC transport factory
│   │   ├── stt.py                 # Deepgram STT factory
│   │   ├── tts.py                 # Cartesia TTS factory
│   │   ├── debug_server.py        # Optional aiohttp debug server (port 8765)
│   │   ├── llm_agent/
│   │   │   ├── agent.py           # LLMAgent; service + context construction
│   │   │   ├── tools.py           # Tool schemas and callback registration
│   │   │   ├── AGENT_BACKGROUND.md    # Stable Ariadne product context
│   │   │   └── CORE_INSTRUCTIONS.md   # Voice constraints and tool-use policy
│   │   ├── coding_agent/
│   │   │   ├── investigator.py    # Investigator; spawns Codex subprocess
│   │   │   ├── doc_writer.py      # DocWriter; generates implementation briefs
│   │   │   ├── handlers.py        # InvestigationTaskHandler, WriteDocTaskHandler
│   │   │   ├── ARIADNE-AGENT-RULES.md     # Rules injected into every Codex prompt
│   │   │   ├── INVESTIGATION_PROMPT.md    # Codex investigation prompt template
│   │   │   └── BRIEF_PROMPT.md            # Implementation brief prompt template
│   │   └── utils/
│   │       └── paths.py           # ARIADNE_HOME, logs dir, briefs dir helpers
│   ├── pyproject.toml
│   ├── .env.example
│   └── Dockerfile
├── tools/
│   ├── register-dialin.sh
│   ├── refresh_project_background.sh
│   ├── build-deploy.sh
│   └── rollback.sh
├── docker-compose.yml
├── .env.example
├── PRIVACY.md
└── README.md
```

