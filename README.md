# Project Aether — MVP

A local-first AI agent foundation with durable task state, configurable model routing, an approval-gated coding workflow, a local review UI, and an optional Docker-based test sandbox.

## Included

- FastAPI local API and OpenAPI docs
- SQLite task journal and durable tool execution records
- Workspace-confined file listing and text search
- OpenAI-compatible model adapter with primary, coding-specialist, and fallback routes
- Bounded retries for transient network, timeout, and HTTP 5xx failures
- Coding proposals with complete-file diffs and persisted approval state
- Explicit approval before proposed file changes are applied
- Stale-file detection and workspace path checks
- Local review UI at `http://127.0.0.1:8000/ui/`
- Optional Docker sandbox for pytest on a disposable workspace snapshot
- GitHub Actions test workflow

## Important safety notes

- Bind the API to localhost only. API authentication is not included yet.
- The UI is a local review surface, not an authentication system. Anyone able to reach the API can call its endpoints.
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

## Configure model providers

- `AETHER_MODEL_BASE_URL`, `AETHER_MODEL_API_KEY`, `AETHER_MODEL_NAME`: default route
- `AETHER_CODING_MODEL_BASE_URL`, `AETHER_CODING_MODEL_API_KEY`, `AETHER_CODING_MODEL_NAME`: optional coding specialist
- `AETHER_FALLBACK_MODEL_BASE_URL`, `AETHER_FALLBACK_MODEL_API_KEY`, `AETHER_FALLBACK_MODEL_NAME`: optional fallback
- `AETHER_DB_PATH`: SQLite database path, default `./data/aether.sqlite3`
- `AETHER_WORKSPACE`: allowed workspace, default `./workspace`
- `AETHER_ENABLE_TEST_RUNNER`: defaults to `false`; set to `true` to enable Docker-backed pytest
- `AETHER_TEST_TIMEOUT_SECONDS`: timeout, clamped to 5–120 seconds
- `AETHER_SANDBOX_IMAGE`: local image name, default `aether-sandbox:latest`

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
- `GET /coding/proposals/{proposal_id}`
- `POST /coding/proposals/{proposal_id}/approve`
- `POST /coding/proposals/{proposal_id}/reject`
- `POST /coding/proposals/{proposal_id}/apply`
- `GET /coding/files?path=.`
- `POST /coding/run-tests`

## Reliability behavior

- SQLite WAL persistence for tasks, tool executions, and coding proposals.
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

1. Add local API authentication and CSRF/origin safeguards before allowing non-local access.
2. Run security tests against the full approval/apply flow, including concurrent requests and crashes.
3. Add a safe iterative coding loop that generates a proposal, runs sandbox tests, summarizes failures, and asks for approval before applying any new patch.
4. Add session history and controlled memory retrieval.
5. Benchmark latency, reliability, and cost before enabling automatic cost-based routing.
