# AETHER CLAW — Competition Demo Runbook

This runbook is a repeatable, honest demonstration of the current MVP. It showcases local control, model routing, explicit review of coding changes, and optional isolated testing. It does not claim that the agent is fully autonomous or that cloud-model requests remain on the machine.

## Demo goal

Show one end-to-end flow:

1. Start the API on loopback and verify health.
2. Show configured model routes without exposing credentials.
3. Send a short chat request.
4. Select existing files in the configured workspace and generate a coding proposal.
5. Review the diff, then explicitly approve and apply it.
6. If Docker testing is enabled and the sandbox image exists, run tests and show the structured result.
7. Optionally demonstrate saved memory as an explicit, user-controlled feature.

**Safety boundary:** never expose the local API to a public network, show provider keys on screen, or approve a diff without reading it. The test runner operates on a disposable snapshot; it is not a guarantee that arbitrary code is safe.

## Before the demo

- [ ] Pull the latest `main` branch and run `python -m pytest -q`.
- [ ] Configure at least one OpenAI-compatible model route in the shell or through the UI's in-memory provider configuration panel.
- [ ] Configure `AETHER_API_TOKEN` and keep the value off-screen; enter it into the UI when prompted.
- [ ] Put a small, non-sensitive sample project with tests inside the configured `AETHER_WORKSPACE`.
- [ ] For the sandbox segment only, build the Docker image and set `AETHER_ENABLE_TEST_RUNNER=true`.
- [ ] Verify that the app binds to `127.0.0.1`, not `0.0.0.0`.
- [ ] Close unrelated windows and remove secrets or personal data from the sample workspace.

Provider variables are read from the process environment. This MVP does not load `.env` automatically. UI-configured provider credentials are memory-only and reset when the server restarts.

## Start and verify

From the repository root, activate the project's virtual environment and export the provider variables you need. Then start the service:

```bash
source .venv/bin/activate
python -m uvicorn aether.app:app --host 127.0.0.1 --port 8000
```

Open these local pages:

- UI: http://127.0.0.1:8000/ui/
- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health

Show `/health` and `/models` only as status information. `/models` reports route IDs/model IDs/configuration status, not API keys. If the token is enabled, enter it in the UI's token field.

## Suggested 4–6 minute walkthrough

### 1. Health and routes (30–45 seconds)

- Open the UI and check that the API is reachable.
- Show which model routes are configured.
- Explain that Auto uses a local heuristic to select task intent; it is not benchmark-driven model optimization.
- If showing Manual mode, select a route that is actually configured.

### 2. Chat and session history (45–60 seconds)

- Ask a small, non-sensitive question that can be answered quickly.
- Show that the conversation is associated with a persistent local session.
- If provider latency is unpredictable, prepare a fallback question and do not promise a fixed response time.

### 3. Proposal-first coding (90–120 seconds)

- Use a small sample repository inside the configured workspace.
- Select only the file or files needed for a simple change.
- Give a precise instruction, for example: “Correct the boundary condition in this function. Preserve the public interface and existing style.”
- Generate the proposal and inspect the summary and diff.
- Point out that proposal generation itself does not modify the selected workspace files.
- Explicitly approve only after reviewing the diff, then apply it.
- Do not use a real personal or production repository for a live demo.

### 4. Test-and-fix / sandbox (60–90 seconds, optional)

- Confirm Docker is running, the configured sandbox image has already been built, and the test runner is enabled.
- Run the test-and-fix workflow or sandboxed pytest action.
- Explain that iterative test-and-fix uses a disposable workspace copy and that a passing candidate still becomes a pending proposal requiring review and approval.
- If Docker or the image is unavailable, skip this segment rather than implying the sandbox ran.

### 5. Explicit memory (30–45 seconds, optional)

- Save a harmless preference or demo note manually.
- Search for it and show the result.
- Explain that saved-memory retrieval is opt-in per chat request and uses lexical keyword matching, not embeddings. Never store secrets in memory.

## Fallback plan

- **Provider unavailable:** demonstrate health, route configuration, workspace listing, and the documented approval-first flow. Clearly state that live model calls are unavailable; do not present a mock response as a real model response.
- **Docker unavailable:** skip the sandbox segment and explain that Docker is optional for the core API but required for the Docker-backed test runner.
- **No sample project:** prepare one in advance. The coding workflow targets explicitly selected existing files and does not support arbitrary shell execution or creating new files through the proposal workflow.
- **Unexpected failure:** capture the exact error, stop the affected segment, and continue only with features that still work. Do not silently claim success.

## Claims to make — and avoid

**Supported by the current MVP**
- Local FastAPI service and SQLite-backed task/session/memory persistence.
- Configurable OpenAI-compatible provider routes with bounded retries and transient-error fallback.
- Explicit review and approval before coding proposals are applied.
- Optional Docker-backed pytest on a disposable snapshot.
- API route discovery that does not return provider credentials.

**Do not claim**
- Fully autonomous or production-ready operation.
- Benchmark-driven automatic model selection or dynamic provider discovery.
- Perfect sandbox isolation or guaranteed safety for hostile code.
- That every inference stays local when a cloud provider is configured.
- That passing tests proves a change is correct in every situation.

## Final checklist

- [ ] Latest test suite passed locally.
- [ ] API health is OK and intended provider route is configured.
- [ ] Demo workspace contains only safe, non-sensitive sample files.
- [ ] API remains bound to loopback.
- [ ] Token and provider keys are not visible in screen recording.
- [ ] Every proposed diff is reviewed before approval.
- [ ] Any skipped or failed segment is described honestly.
