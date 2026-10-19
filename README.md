# Project Aether — MVP

A local-first, modular AI agent foundation focused on reliable task execution.

## Included

- FastAPI local API and interactive OpenAPI docs
- SQLite task journal with durable tool execution records
- Pydantic-validated workspace file listing and text search
- OpenAI-compatible provider adapter
- Model routing: general/reasoning use the default route; coding can use a specialist route
- Optional failover provider for transient timeouts, network errors, and HTTP 5xx responses
- Bounded retries (maximum 3 attempts per configured route)
- GitHub Actions test workflow

## Important limitations

This is a foundation, not a production-ready autonomous agent. It does not run shell commands, edit files, send messages, or automatically replay uncertain actions. No API authentication is included; bind the server to localhost only. Provider routing is rule-based, not an automatic benchmark or cost optimizer.

## Setup

Python 3.11+ recommended.

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env
```

Set environment variables in your shell or load them with your preferred local environment manager. This MVP intentionally does not auto-load `.env`.

## Configuration

- `AETHER_MODEL_BASE_URL`, `AETHER_MODEL_API_KEY`, `AETHER_MODEL_NAME`: default route
- `AETHER_CODING_MODEL_BASE_URL`, `AETHER_CODING_MODEL_API_KEY`, `AETHER_CODING_MODEL_NAME`: optional coding specialist
- `AETHER_FALLBACK_MODEL_BASE_URL`, `AETHER_FALLBACK_MODEL_API_KEY`, `AETHER_FALLBACK_MODEL_NAME`: optional failover route
- `AETHER_DB_PATH`: SQLite database path, default `./data/aether.sqlite3`
- `AETHER_WORKSPACE`: allowed workspace, default `./workspace`

Provider base URLs should be the OpenAI-compatible API prefix, commonly ending in `/v1`. Never commit real API keys.

## Run

```bash
uvicorn aether.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs`.

## API examples

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/tools
```

General chat:

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Explain Python virtual environments","task_type":"general"}'
```

Coding request (uses the coding route if configured):

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Review this function for bugs","task_type":"coding"}'
```

## Reliability behavior

- Task and tool-execution records are durable in SQLite with WAL mode.
- On startup, in-flight records are marked `unknown`; Aether never blindly replays potentially side-effecting work.
- Provider retries are bounded and apply only to transient network errors, timeouts, and HTTP 5xx errors.
- Authentication/configuration errors and ordinary 4xx responses are not retried.
- Failover is attempted only for transient errors; route metadata includes selected route, model name, fallback usage, and attempt count.
- Tool paths are resolved and constrained to the configured workspace.

## Tests

```bash
pytest -q
```

## Next milestones

1. Add approval and authentication boundaries.
2. Add sandboxed coding execution with timeouts and resource limits.
3. Add session history and controlled memory retrieval.
4. Add idempotency keys and stronger crash/concurrency tests.
5. Benchmark latency, reliability, and cost before enabling automatic cost-based routing.
6. Add a messaging adapter after core reliability tests pass.
