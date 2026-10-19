# Project Aether — MVP

A local-first AI agent foundation with durable task state, configurable model routing, an approval-gated coding workflow, a local review UI, and an optional Docker-based test sandbox.

## Included

- FastAPI local API and OpenAPI docs
- Optional API bearer token and same-origin checks for state-changing requests
- SQLite-backed explicit long-term memory with category/tag search and deletion
- Persistent conversation sessions and message history
- Opt-in saved-memory retrieval per chat request; stored text is marked as untrusted reference data
- SQLite task journal and durable tool execution records
- Workspace-confined file listing and text search
- OpenAI-compatible model adapter with primary, coding-specialist, and fallback routes
- Bounded retries for transient network, timeout, and HTTP 5xx failures
- Coding proposals with complete-file diffs and persisted approval state
- Bounded test-and-fix loop (up to 3 rounds) on a disposable workspace copy; only a passing candidate becomes a pending proposal
- Explicit approval before proposed file changes are applied
- Stale-file detection and workspace path checks
- Local review UI at `http://127.0.0.1:8000/ui/`
- Optional Docker sandbox for pytest on a disposable workspace snapshot
- GitHub Actions test workflow

## Important safety notes

- Bind the API to localhost only. Set `AETHER_API_TOKEN` to require a shared token for API routes; health, UI assets, and API schema/docs remain reachable without the token.
- The local UI stores the entered token in this browser tab's session storage and sends it in the `X-Aether-Token` header. Do not expose this unauthenticated static UI or the API to a public network.
- When no token is configured, API requests are allowed only from loopback clients. This is a development fallback, not authentication against other local processes.
- State-changing requests with an Origin header must use the same loopback host and port. This is defense in depth, not a substitute for keeping the service local.
- Coding proposals only edit explicitly selected, existing files. New-file creation and arbitrary shell access are not supported.
- The Docker test runner is disabled by default. When enabled, it requires a prebuilt local image, disables networking, drops Linux capabilities, runs as an unprivileged UID, sets resource limits, uses a read-only container root, and tests a disposable copy of the workspace.
- Docker isolation is a useful layer, not a perfect security boundary. Keep Docker and the host patched. Do not run hostile workloads on a sensitive machine.
- The sandbox snapshot rejects file symlinks and excludes common generated/dependency directories. The configured workspace should still be treated as trusted input.
- Provider routing is rule-based; automatic benchmark-based cost routing is not yet implemented.

## Setup

Python 3.11+ and Docker are recommended.

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell:
# .venv\\Scripts\\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env
```

Environment variables are read from the process. This MVP does not load `.env` automatically; export the values with your preferred local environment manager.

Generate a local API token:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
export AETHER_API_TOKEN='paste-generated-token-here'
```

On PowerShell, set `$env:AETHER_API_TOKEN="paste-generated-token-here"`. Start the server after setting the variable, then paste the same token into the UI's API token field. Never commit the token to Git.

## Configure model providers

- `AETHER_MODEL_BASE_URL`, `AETHER_MODEL_API_KEY`, `AETHER_MODEL_NAME`: default route
- `AETHER_CODING_MODEL_BASE_URL`, `AETHER_CODING_MODEL_API_KEY`, `AETHER_CODING_MODEL_NAME`: optional coding specialist
- `AETHER_FALLBACK_MODEL_BASE_URL`, `AETHER_FALLBACK_MODEL_API_KEY`, `AETHER_FALLBACK_MODEL_NAME`: optional fallback
- `AETHER_DB_PATH`: SQLite database path, default `./data/aether.sqlite3`
- `AETHER_WORKSPACE`: allowed workspace, default `./workspace`
- `AETHER_ENABLE_TEST_RUNNER`: defaults to `false`; set to `true` to enable Docker-backed pytest
- `AETHER_TEST_TIMEOUT_SECONDS`: timeout, clamped to 5–120 seconds
- `AETHER_SANDBOX_IMAGE`: local image name, default `aether-sandbox:latest`
- `AETHER_API_TOKEN`: optional shared token required for API routes; leave unset only for loopback-only development

Never commit real API keys.

## Build the sandbox image

Build once from the repository root. Runtime uses `--pull=never`, so it will not pull images automatically.

```bash
docker build -f Dockerfile.sandbox -t aether-sandbox:latest .
```

Then set these environment variables in your local shell:

```bash
export AETHER_ENABLE_TEST_RUNNER=true
export AETHER_SANDBOX_IMAGE=aether-sandbox:latest
```

PowerShell:

```powershell
$env:AETHER_ENABLE_TEST_RUNNER="true"
$env:AETHER_SANDBOX_IMAGE="aether-sandbox:latest"
```

The test endpoint creates a temporary copy of the configured workspace and runs pytest in Docker with `--network=none`, `--read-only`, `--cap-drop=ALL`, `no-new-privileges`, a non-root UID, a PID limit, memory/CPU limits, a bounded timeout, and a temporary filesystem for `/tmp`. Changes made by tests are discarded with the temporary snapshot.

## Run the API and UI

```bash
uvicorn aether.app:app --host 127.0.0.1 --port 8000
```

- Local UI: `http://127.0.0.1:8000/ui/`
- API docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

## Coding workflow via UI

1. Put the project you want to work on inside the configured workspace.
2. Open the local UI and select existing files.
3. Describe the requested change and generate a proposal.
4. Review the diff.
5. Approve the proposal, then apply it.
6. If configured, run tests in the disposable Docker sandbox.

Equivalent API endpoints:
- `POST /coding/proposals`
- `POST /coding/iterate` with `instruction`, `paths`, and optional `max_rounds` (1–3)
- `GET /coding/proposals/{proposal_id}`
- `POST /coding/proposals/{proposal_id}/approve`
- `POST /coding/proposals/{proposal_id}/reject`
- `POST /coding/proposals/{proposal_id}/apply`
- `GET /coding/files?path=.`
- `POST /coding/run-tests`

## Chat sessions and memory-aware context

The local UI includes persistent chat sessions. Each chat message is saved in SQLite and the latest 12 prior user/assistant messages are passed to the configured model on follow-up turns. The UI lets you create a new chat, reopen a saved chat, and delete a conversation with its messages.

Saved memory use is **off by default for each request**. Check the opt-in box to retrieve up to five keyword-matched records for that message. Memory records are added as explicitly labeled untrusted reference data, not as instructions. The model provider still receives the selected conversation text and any explicitly enabled memory records, so do not store secrets in chat or memory. This is lexical retrieval, not embeddings.

API routes:
- `POST /sessions` to create a session
- `GET /sessions` to list sessions
- `GET /sessions/{session_id}` to fetch messages
- `DELETE /sessions/{session_id}` to delete a session and its messages
- `POST /chat` with `message`, optional `session_id`, `task_type`, and `use_saved_memories` (default `false`)

## Long-term memory

Memory is explicit and local, not an automatic model context feed. Use the UI's memory section or these API routes:

- `POST /memory` to save `{ "category": "preference", "content": "...", "tags": ["..."], "source": "user" }`
- `GET /memory?limit=100&category=preference` to list saved memories
- `POST /memory/search` to perform local keyword search
- `DELETE /memory/{memory_id}` to delete a record

Memory search is lexical keyword matching, not embeddings or semantic retrieval. The app does not silently infer or store user memories from chats.

## Reliability behavior

- SQLite WAL persistence for tasks, tool executions, coding proposals, sessions, session messages, and saved memories.
- In-flight tasks/tool executions are marked `unknown` on startup; potentially side-effecting work is not replayed automatically.
- Provider retries are bounded and restricted to transient failures.
- Coding proposal application checks original file hashes before replacing files.
- The sandbox does not use network access and never pulls an image at runtime.

## Tests

```bash
pytest -q
```

The test suite includes unit tests for workspace path restrictions, proposal approval, stale-file detection, and sandbox command configuration. GitHub Actions runs the test suite, but the latest CI result should be checked on the Actions page before treating a branch as verified.

## Next milestones

1. Run security tests against the full approval/apply flow, including concurrent requests and crashes.
2. Add session history and optional, user-approved memory retrieval into model context.
3. Benchmark latency, reliability, and cost before enabling automatic cost-based routing.
