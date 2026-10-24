# OpenJiuwen Proposal Submission — AETHER CLAW

> Working draft for the 30 October 2026 deadline. Check against the final recorded demo before submission.

## Project name
**AETHER CLAW — a local-first AI agent for controlled, verifiable task execution**

## Overview
AETHER CLAW is a modular AI-agent foundation designed to make AI-assisted work safer to inspect and recover. Instead of silently changing a project, it separates proposal from execution, records task and tool states in SQLite, and requires explicit user approval for code changes. It supports configurable OpenAI-compatible model routes, optional local-model fallback, workspace-scoped file tools, persistent chat sessions and explicit memory, and an optional Docker-based test runner.

This is an evolving MVP, not a production-ready autonomous agent. The submission focuses on a demonstrable developer workflow: propose a code change, validate it in an isolated disposable copy, review the diff, then decide whether to apply it.

## Problem and target scenario
AI coding assistants can produce plausible edits, but developers still need to know what changed, whether tests pass, whether the intended files were touched, and what happens if execution is interrupted.

**Scenario:** a solo developer asks AETHER CLAW to improve a small function in an existing local project. The agent reads selected workspace files, creates a reviewable proposal, and—when the optional Docker runner is enabled—tests the candidate against a disposable snapshot. A passing candidate remains pending for explicit approval; the original workspace is not silently overwritten by the test-and-fix loop.

## Technical approach

### 1. Local-first service and model routing
- FastAPI service intended to bind to loopback (`127.0.0.1`).
- Configurable primary, coding-specialist, optional reasoning-specialist, and fallback model routes using OpenAI-compatible APIs.
- Auto/manual route selection and bounded retries for selected transient provider failures.
- Provider credentials are configured through the process environment or in-memory route configuration; route discovery does not return credentials.

### 2. Durable task and session state
- SQLite stores task records, tool-execution records, coding proposals, sessions, messages, and explicit memories.
- Interrupted task/tool records are marked `unknown`, rather than blindly replayed when outcomes may be uncertain.
- Coding proposals use guarded state transitions, an apply claim, and a local OS file lock to reduce duplicate concurrent applies.
- Interrupted applies are flagged for manual workspace reconciliation rather than silently re-approved.

### 3. Review-first coding workflow
- The coding engine accepts a bounded list of existing workspace files and rejects path traversal, symlink paths, duplicate paths, and oversized inputs.
- Model output is validated and normalized into per-file changes and diffs.
- Changes are not applied until the user explicitly approves the proposal.
- Original file content hashes are checked to detect stale proposals.
- The iterative test-and-fix workflow works on a disposable copy, is bounded to at most three rounds, and returns a pending proposal only when the candidate passes.
- The optional Docker test runner uses a disposable snapshot with networking disabled and additional container restrictions. Docker is defense in depth, not a perfect security boundary.

### 4. Safety and limitations
- Local API protection supports a shared token and same-origin checks for state-changing requests.
- Workspace tools are scoped to the configured workspace.
- Saved-memory retrieval is opt-in per chat request; memory search is keyword-based in the current MVP.
- The project does not yet implement every feature of a fully autonomous agent: general browser automation, mobile nodes, a full multi-step workflow engine, a knowledge graph, and autonomous reinforcement learning are not completed features.
- Keep the service local; do not expose it to a public network.

## Engineering checkpoint — 24 October 2026

The three 23–24 October hardening tasks are **implemented on the default branch and have regression coverage**:

- **SQLite schema migration:** the legacy coding-proposal table is migrated transactionally to support the `applying` state while preserving existing proposal data. A forced migration failure is tested to confirm rollback leaves the legacy schema and rows intact.
- **Atomic apply protection:** proposal claiming uses a conditional database transition from `approved` to `applying`, and a local OS file lock serializes apply/recovery across processes. Regression tests cover single-claim behavior and concurrent apply attempts.
- **Failure and rollback tests:** tests cover a multi-file replacement failure restoring prior file contents, an unsuccessful rollback remaining flagged for manual review, and failure to persist the final `applied` status without pretending the operation was rolled back.

Relevant regression coverage is in `tests/test_store.py`, `tests/test_coding.py`, and `tests/test_coding_approval_safety.py`.

**Validation evidence:** GitHub Actions “Tests” run **#413** completed successfully for commit `fc09e6b`, which was subsequently merged to the default branch as `8fe2125`. This is useful evidence for the current implementation, but it does **not** replace running the complete test suite on the exact final submission commit. The final-commit test run remains a release gate.

## Updated plan to the 30 October 2026 deadline

| Date | Priority | Exit criterion |
|---|---|---|
| **24 Oct** | Close the schema-migration, atomic-apply, and failure/rollback hardening tasks; record evidence. | **Complete:** implementation and regression tests are present; the referenced CI run passed. |
| **25 Oct** | Review open PRs and recent changes; address only reproducible correctness/security defects. Avoid new feature scope. | No unreviewed change is required for the core demo; all PRs intended for submission have an explicit decision. |
| **26 Oct** | Verify setup from a clean checkout and review configuration, API-token handling, workspace boundaries, and README claims. | Fresh setup instructions work without exposing secrets; limitations are documented accurately. |
| **27 Oct** | Run the full test suite on a release-candidate commit. Build and exercise the Docker sandbox if the demo will claim sandbox execution. | Save the exact commit SHA, command, complete result, and sandbox result (or omit the sandbox claim). |
| **28 Oct** | Record the demo from the actual application and review the export. | Demo is at most 3 minutes, uses non-sensitive data, contains no visible credentials, and every shown result is real. |
| **29 Oct** | Freeze scope, fill final metadata, upload the materials, and target submission. | Repository link, tested commit, test result, demo URL, and portal confirmation are recorded. |
| **30 Oct** | Deadline contingency only: fix a submission-blocking defect, rerun affected tests, and submit. | Submission completed before the deadline; do not add optional features. |

The remaining work is **release verification and submission preparation**, not implementation of the three hardening tasks. If a test or demo step fails, fix the root cause and re-run the relevant checks rather than lowering coverage or making unsupported claims.

## Demo plan (maximum 3 minutes)
The recording must show behavior that works on the final submission commit. Use a disposable test project and non-sensitive sample data. Never show API keys or tokens.

| Time | Show | Proof / narration |
|---|---|---|
| 0:00–0:20 | Introduce AETHER CLAW and local health status | Local-first agent focused on controlled execution, explicit approval, and recoverable state. |
| 0:20–0:45 | Show configured model routes without secrets | Explain specialist routing and optional fallback. |
| 0:45–1:20 | Submit a small coding task and inspect proposal diff | Only selected files are eligible; proposal is pending review. |
| 1:20–1:55 | Run test-and-fix on a disposable test project | Show actual test result and state whether Docker is enabled. |
| 1:55–2:25 | Show pending proposal and approval boundary | Passing candidate is still not applied automatically. |
| 2:25–2:45 | Show database health or persisted task/session state | Pick one stable, verified screen. |
| 2:45–3:00 | Close with value proposition and MVP scope | “Propose, test, review, then apply—without pretending uncertain work succeeded.” |

If a step is not verified on the final commit, omit it rather than simulate success. Keep the exported video at or below 3:00.

## Submission checklist
- [ ] Confirm final branch/commit and clean working tree.
- [ ] Run the complete test suite on the exact submission commit; save the command and result.
- [ ] Build and verify the optional Docker sandbox if the demo claims sandbox execution.
- [ ] Record the demo from the actual running application; verify duration ≤ 3:00 and no secrets are visible.
- [ ] Review video and documentation for claims that exceed implemented behavior.
- [ ] Include repository link, overview/technical approach, demo video, and required submission metadata.
- [ ] Submit one entry before 30 October 2026; target 29 October to leave time for upload/validation.

## Final metadata to fill before submission
- Repository URL: https://github.com/bLACKtERMINAL737/AETHER-AGENT
- Exact submission commit: _fill after final code freeze_
- Test command and result: _fill after running on the exact submission commit_
- Demo video URL: _fill after recording and uploading_
- Submission portal confirmation: _fill after submission_
