# Ariadne Privacy and Safety Notes

Ariadne is a local-first, voice-first engineering thought partner. This document
describes what data Ariadne creates, where it is stored, and what may leave your
machine depending on the providers you configure.

## What Ariadne Does

Ariadne runs a voice bot locally on your workstation. During a call it can:

- Receive your voice and transcribe it to text.
- Send text turns to a language model to generate responses.
- Speak responses back over audio.
- Inspect a selected local repo in read-only mode via a code investigation agent.
- Generate a Markdown implementation brief and save it to the repo.

## What Stays Local By Default

All of the following are written only to your local machine:

| Artifact | Default location |
|---|---|
| Session logs and event timelines | `~/.ariadne/logs/session-logs/<session-id>/` |
| Call transcripts | `~/.ariadne/logs/session-logs/<session-id>/transcript.md` |
| Project background cache | `~/.ariadne/project-backgrounds/<repo-name>-<hash>/` |
| Implementation briefs | `<repo>/.ariadne/briefs/` |
| Repo investigation output | Inside session logs (see above) |

These paths can be overridden with environment variables. See `bot/.env.example`
for the full list.

## What May Leave Your Machine

The following data may be sent to external cloud providers, depending on which
providers are configured:

| Data | Provider |
|---|---|
| Call audio | Daily (WebRTC / PSTN infrastructure) |
| Speech-to-text transcription | Deepgram (or configured STT provider) |
| Conversation turns and repo findings | OpenAI (or configured LLM provider) |
| Text-to-speech generation | Cartesia (or configured TTS provider) |
| Repo investigation prompts and findings | OpenAI Codex CLI (or configured code agent) |

Ariadne does not make any additional network calls beyond what the above providers
require. There is no Ariadne cloud service receiving your data.

Do not assume "local-only" unless you have replaced all providers with locally
hosted alternatives.

## Repo Access

Ariadne's repo investigator is designed to be read-only:

- It may list files, read source, inspect tests, and read non-secret config.
- It should not edit, create, delete, commit, push, deploy, or migrate.
- It is instructed to avoid `.env`, private keys, credentials, tokens, and any
  file that appears secret-bearing.

These are enforced through runtime rules and sandboxing where available, but no
technical measure is perfectly complete. Review `bot/ariadne/ARIADNE-AGENT-RULES.md`
for the exact rules passed to the investigator.

## Company Repos Warning

> Do not use Ariadne with employer-owned, confidential, or proprietary repositories
> unless you are authorized to do so and your organization permits the configured
> AI providers to process this kind of data.

## Logs Warning

Local logs and transcripts can contain sensitive engineering context: code structure,
architecture decisions, implementation plans, and fragments of file content surfaced
during investigation. Treat the `~/.ariadne/` directory with the same care as source
code or internal documentation.

## Cleanup

To remove all Ariadne operational artifacts:

```bash
rm -rf ~/.ariadne
```

To remove implementation briefs from a specific repo:

```bash
rm -rf /path/to/repo/.ariadne
```

Note: deleting `<repo>/.ariadne` removes any implementation briefs written
during Ariadne sessions for that repo.
