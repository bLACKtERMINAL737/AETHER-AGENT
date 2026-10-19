# Project Aether — MVP

A local-first, modular AI agent foundation focused on reliable task execution.

## Included

- FastAPI local API
- SQLite task journal with durable tool execution records
- Tool registry with Pydantic input validation
- Workspace-confined file listing and text search
- Optional OpenAI-compatible chat provider adapter
- Explicit approval boundary for write/execute tools (not implemented in this MVP)
- Tests for persistence, workspace boundaries, and tool validation

## Not included yet

This is a foundation, not a production-ready autonomous agent. It does not yet run shell commands, edit files, send messages, schedule tasks, or autonomously retry uncertain external actions. Those features should be added only with sandboxing and approval policies.

## Setup

Python 3.11+ recommended.

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1

pip install -e ".[dev]"
cp .env.example .env
```

Set `AETHER_MODEL_BASE_URL`, `AETHER_MODEL_API_KEY`, and `AETHER_MODEL_NAME` in `.env` if you want to connect an OpenAI-compatible provider. If these are absent, the API still works for health checks and tools; `/chat` returns a clear configuration error.

## Run

```bash
uvicorn aether.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs`.

The server binds to localhost by default. Do not expose it to a network without adding authentication.

## API examples

Health:

```bash
curl http://127.0.0.1:8000/health
```

List workspace files:

```bash
curl -X POST http://127.0.0.1:8000/tools/workspace.list_files \
  -H 'Content-Type: application/json' \
  -d '{"path":"."}'
```

Create a task journal entry:

```bash
curl -X POST http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title":"Inspect project","input":"List the files and summarize the structure"}'
```

Chat (requires provider environment variables):

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Explain what a Python virtual environment is"}'
```

## Configuration

Environment variables are read from the process environment. Copy `.env.example` to `.env`, then export values in your shell; automatic `.env` loading is intentionally not included in this minimal version.

- `AETHER_DB_PATH`: SQLite database location, default `./data/aether.sqlite3`
- `AETHER_WORKSPACE`: directory allowed for workspace tools, default `./workspace`
- `AETHER_MODEL_BASE_URL`: base URL for an OpenAI-compatible API
- `AETHER_MODEL_API_KEY`: API key
- `AETHER_MODEL_NAME`: model identifier

## Reliability design

- Task state and tool execution records are stored separately from conversation context.
- SQLite uses WAL mode and transactions for local persistence.
- Tool execution records use explicit states.
- This MVP does not automatically replay a `running` tool after restart. It marks the outcome as `unknown`, because replaying an action without checking its effects can create duplicates.
- Tool input is validated before dispatch.
- Workspace paths are resolved and checked to prevent escaping the configured workspace.

## Tests

```bash
pytest
```

## Next milestones

1. Add authentication and a user approval workflow.
2. Add a sandboxed coding executor (Docker or a similarly isolated backend).
3. Add provider-aware error classification and bounded retries.
4. Add session history and controlled memory retrieval.
5. Add crash-injection tests and performance benchmarks.
6. Add one messaging adapter only after core reliability tests pass.
