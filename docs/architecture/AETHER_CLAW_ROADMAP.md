# AETHER CLAW: Architecture Audit and Delivery Roadmap

**Status:** Planning baseline, 2026-10-26  
**Target:** Deliver a reviewable first increment by 2026-10-29; evolve the system over the following six weeks.  
**Principle:** Ship tested, bounded capabilities—not claims of parity based on a feature checklist.

## Current architecture (verified from `main`)

- FastAPI application currently initializes configuration, providers, SQLite task store, tools, and coding engine at module import time.
- `ModelProvider` speaks an OpenAI-compatible chat-completions API, including bounded tool calls. `ModelRouter` routes among primary, coding, reasoning, and fallback providers.
- SQLite persists tasks, tool executions, coding proposals, memories, sessions, and session messages. Task claiming is atomic; interrupted outcomes are marked unknown rather than blindly replayed.
- Specialist roles are registered and validated, but `/agents/orchestrate` currently runs planned subtasks sequentially and the agents are analysis-only. This is not yet a general autonomous multi-agent runtime.
- Coding changes use proposals and explicit approval. Optional tests run in a disposable Docker snapshot.
- Workspace tools include constrained file operations and web search/open. A general browser automation runtime, MCP client, reusable skill loader, scheduled-job service, and messaging gateways are not established as core capabilities in the inspected baseline.
- Existing tests on the user's latest local main were reported as 254 passing; rerun CI against the exact PR head before merging any code.

## Main architectural gaps and risks

1. **Orchestration:** sequential execution limits throughput; no first-class dependency graph, concurrency budget, cancellation propagation, or durable parent/child run model is evident in the current role registry.
2. **Recovery semantics:** the journal deliberately avoids replaying uncertain work, which is safe, but needs explicit retry/idempotency policies and operator-visible recovery actions before becoming a durable autonomous runtime.
3. **Runtime boundaries:** app globals couple configuration and service lifecycle, making isolated tests and multiple runtime modes harder.
4. **Tool safety:** tool schemas and workspace boundaries are a useful start. Any new browser, MCP, shell, or messaging capability must add per-tool permissions, timeouts, audit events, secret redaction, and approval gates for consequential actions.
5. **Skills and memory:** saved memory and session search exist, but a versioned, validated, reusable skill format and evidence-based skill evaluation loop need to be designed separately.
6. **Evaluation:** a passing unit suite is necessary but does not demonstrate agent quality. Add deterministic orchestration tests plus a small reproducible benchmark suite for success rate, latency, token/cost estimates, tool errors, and unsafe-action rejection.

## Delivery plan

### By 2026-10-29: first reviewable increment
- Establish this architecture baseline and acceptance criteria.
- Add tests around bounded parallel subtask execution, task-state transitions, partial failure, cancellation/timeout, and stable result ordering before enabling concurrency in the API.
- Implement only a small, configurable concurrency cap; keep external actions and workspace modifications approval-gated.
- Ensure orchestration returns per-subtask status and never reports overall success when required work failed.
- Run the full test suite and document exact results, limitations, and rollback behavior.
- Submit a PR; do not merge automatically.

### Week 1–2: reliable agent runtime
- Introduce a service boundary between API routes, orchestration, persistence, provider routing, and tool execution.
- Model parent runs, child tasks, dependencies, budgets, deadlines, cancellation, retries, and idempotency explicitly.
- Keep SQLite for the local-first MVP. Evaluate a durable workflow engine only if restart/retry requirements justify its operational cost.

### Week 2–3: skills and knowledge
- Add a versioned, directory-based skill format with metadata, explicit tool requirements, input/output contracts, validation, and provenance.
- Treat skill content and retrieved memory as untrusted data, not policy. Require user approval before a skill can gain permissions or perform consequential actions.
- Evaluate skill changes against regression cases before marking them as learned improvements.

### Week 3–4: browser and integrations
- Add browser automation behind a dedicated isolated runtime, with domain allowlists, navigation/download limits, and user confirmation for purchases, sending messages, account changes, and other external side effects.
- Add an MCP client only after defining tool identity, permission mapping, timeouts, result-size limits, audit logs, and secret handling.

### Week 4–6: operations and evaluation
- Add persistent schedules with run history, misfire policy, and duplicate-run protection.
- Add optional messaging connectors behind explicit opt-in and per-channel permissions.
- Benchmark local and hosted providers by task class; optimize cost/latency only after collecting reproducible measurements.
- Consider PostgreSQL or a durable workflow backend only when multi-process/multi-host requirements demand it.

## Architecture decisions (initial)

- **Keep:** FastAPI, Pydantic validation, OpenAI-compatible provider abstraction, SQLite for local deployment, proposal-first coding, Docker-based disposable test runs.
- **Add incrementally:** bounded async orchestration, parent/child run model, cancellation/deadline propagation, structured run events, skills interface, browser/MCP adapters, scheduler, benchmark harness.
- **Do not add yet:** a heavyweight distributed workflow stack, vector database, or multiple execution runtimes without a measured requirement. Start with SQLite FTS/keyword retrieval and introduce embeddings only when evaluated retrieval tests show a need.
- **Non-negotiable:** no automatic merge; no silent replay of unknown side effects; least privilege; no secrets in logs; approval before external or destructive actions.

## Acceptance criteria for the first increment

- Concurrency has a hard configured upper bound.
- Invalid plans are rejected before any tasks are created.
- Every child task ends in an explicit status, including failures and timeouts.
- Partial failure is surfaced accurately; no false all-success response.
- Results remain associated with their original subtask even when completion order differs.
- Cancellation and provider errors do not leave tasks falsely marked successful.
- Tests cover concurrency limit, mixed success/failure, timeout/cancellation, invalid plan, and result ordering.
- Full test suite and CI status are recorded on the PR.
