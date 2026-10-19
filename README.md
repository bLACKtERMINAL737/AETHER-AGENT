# Project Aether — MVP

A local-first AI agent foundation with durable task state, configurable model routing, and an approval-gated coding workflow.

## Included

- FastAPI local API and OpenAPI docs
- SQLite task journal and durable tool execution records
- Workspace-confined file listing and text search
- OpenAI-compatible model adapter with primary, coding-specialist, and fallback routes
- Bounded retries for transient network, timeout, and HTTP 5xx failures
- Coding proposals with complete-file diffs and persisted approval state
- Explicit approval before proposed file changes are applied
- Stale-file detection so a proposal cannot overwrite a file changed after it was generated
- GitHub Actions tests

## Important safety limitations

- This is not production-ready autonomous computer control.
- No shell tool is exposed by the general tool registry.
- Coding changes are proposal-first and require an explicit approval endpoint before apply.
- Test execution is disabled by default. If enabled, it runs pytest as a subprocess with a timeout, but it is not OS-sandboxed and tests can execute arbitrary project code. Use only in a trusted workspace; for untrusted code, use a container/VM with no secrets and resource limits.
- No API authentication is included. Bind to localhost only and do not expose this API to your network.
- Provider routing is rule-based; automatic benchmark-based or cost-based model selection is not yet implemented.

## Setup

Python 3.11+ recommended.

    python -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"
    cp .env.example .env

Environment variables are read from the process. Load .env using your preferred local environment manager; this MVP does not load it automatically.

## Configuration

- AETHER_MODEL_BASE_URL, AETHER_MODEL_API_KEY, AETHER_MODEL_NAME: default route
- AETHER_CODING_MODEL_BASE_URL, AETHER_CODING_MODEL_API_KEY, AETHER_CODING_MODEL_NAME: optional coding specialist
- AETHER_FALLBACK_MODEL_BASE_URL, AETHER_FALLBACK_MODEL_API_KEY, AETHER_FALLBACK_MODEL_NAME: optional fallback
- AETHER_DB_PATH: database path, default ./data/aether.sqlite3
- AETHER_WORKSPACE: permitted workspace, default ./workspace
- AETHER_ENABLE_TEST_RUNNER: defaults to false; enables pytest subprocess endpoint when true
- AETHER_TEST_TIMEOUT_SECONDS: test timeout, clamped to 5–120 seconds

Never commit real API keys.

## Run

    uvicorn aether.app:app --host 127.0.0.1 --port 8000

Open http://127.0.0.1:8000/docs.

## Coding workflow

The files to edit must already exist in the configured workspace. Proposal generation only reads selected files and stores a diff; it does not change files.

1. Create a proposal with POST /coding/proposals using JSON: {"instruction":"Fix the bug in this function","paths":["src/example.py"]}.
2. Review summary, changes[].diff, and the target paths.
3. Approve with POST /coding/proposals/PROPOSAL_ID/approve.
4. Apply with POST /coding/proposals/PROPOSAL_ID/apply only after reviewing the proposal.
5. Test with POST /coding/run-tests (disabled by default; see warning above).

Other endpoints: GET /coding/proposals/{proposal_id}, POST /coding/proposals/{proposal_id}/reject, POST /chat, and GET /health.

## Reliability behavior

- SQLite WAL persistence for tasks, tool executions, and coding proposals.
- In-flight tasks/tool executions are marked unknown on startup; potentially side-effecting work is not replayed automatically.
- Provider retries are bounded and restricted to transient failures.
- Workspace paths are resolved and constrained to the configured workspace.
- Proposal application checks each original file's SHA-256 before replacing it.
- New files and arbitrary path creation are intentionally not supported in the first coding engine version.

## Tests

    pytest -q

## Next milestones

1. Add API authentication and a local UI for reviewing diffs and approvals.
2. Add a true OS/container sandbox for tests and coding execution.
3. Add idempotency and crash/concurrency tests for proposal application.
4. Add session history and controlled memory retrieval.
5. Benchmark latency, reliability, and cost before enabling automatic cost-based routing.
6. Add messaging integrations after core security boundaries are reviewed.
