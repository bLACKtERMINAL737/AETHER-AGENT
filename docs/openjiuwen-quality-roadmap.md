# AETHER CLAW — OpenJiuwen Competition and Engineering Roadmap

**Planning date:** 24 October 2026  
**Proposal deadline:** 30 October 2026  
**Proposal review milestone:** by 15 November 2026  
**Demo development period:** November–December 2026  
**Demo review:** January 2027 (exact date not yet announced)

This is an internal engineering plan, not a claim that planned capabilities are implemented or that shortlisting is guaranteed.

## Immediate objectives

1. Submit a complete, accurate competition proposal by 30 October.
2. Prepare the demo and supporting evidence before submission, rather than waiting until implementation is finished.
3. Reach a convincing, reproducible prototype state by 15 November.
4. Continue developing the full 24-capability roadmap without trading away security, correctness, reliability, or maintainability.

## Submission checklist (30 October)

- [ ] Project name and concise overview
- [ ] Target users, concrete application scenario, and pain points
- [ ] Technical approach and architecture diagram
- [ ] Innovation claims tied to observable behavior or evidence
- [ ] Demo of no more than three minutes, showing only verified behavior
- [ ] Project documentation and source-code/repository reference
- [ ] Screenshots, test output, and a repeatable demo setup
- [ ] Review of originality, third-party dependencies, data rights, and competition IP terms
- [ ] Submission confirmation saved

Aim to have the complete submission pack ready on 29 October as an internal buffer. Verify the organizer's actual portal closing time and registration requirements; do not assume an unpublished time zone or closing hour.

## Current baseline and honest claims

The project currently has a local-first FastAPI foundation, SQLite-backed sessions and explicit memory, workspace file/search tools, provider routing with bounded retries/fallback, proposal-first coding changes, explicit approval, and an optional disposable Docker pytest sandbox.

Recent local development results were reported as 144 passing tests on mainline and 149 on the cross-session-search branch. These are historical reports, not a guarantee that the current checkout or CI is green; rerun tests on the exact commit used for the demo.

Cross-session search is currently lexical, not semantic. Browser automation, broad terminal execution, messaging, mobile nodes, autonomous skill improvement, and RL integration must not be described as complete unless implementation and tests demonstrate that status.

## Milestones

### 24–26 October: Scope and proposal
- Freeze one primary scenario: a safety-conscious coding agent that proposes changes, requires approval, runs tests in an isolated disposable environment, and reports verified results.
- Audit the current branch and pending cross-session-search pull request.
- Draft overview, users/problem, architecture, novelty, limitations, and implementation plan.
- Start collecting real demo evidence early; keep a fallback recording of already verified behavior.

### 27–29 October: Evidence and finalization
- Exercise the primary workflow from a clean, documented setup.
- Capture test results, API/UI evidence, and failure/safety behavior.
- Edit the demo to fit the organizer's maximum duration of three minutes.
- Complete documentation and check every claim against the actual code.
- Freeze risky feature work by 29 October; prioritize submission correctness over last-minute scope expansion.

### 30 October: Submit
- Submit the proposal and required materials.
- Save the confirmation and an exact copy of submitted files.

### 31 October–7 November: Reliability sprint
- Re-run the complete test suite and establish a repeatable benchmark harness.
- Prioritize crash/recovery, concurrency, provider failures, stale-file conflicts, sandbox behavior, and observability.
- Record baseline task success, failure categories, latency, cost, and regressions before optimizing.

### 8–15 November: Shortlist-readiness sprint
- Improve the same end-to-end coding workflow, not feature count for its own sake.
- Add reproducible benchmark cases and evidence for reliability and safety.
- Prepare a clean setup and demo that another person can reproduce.
- Monitor official competition updates; selection is not guaranteed.

### November–December: Expand capabilities in dependency order
1. Reliable execution foundation: terminal backend abstraction, controlled file operations, browser automation, persistent memory, scheduling, and multi-step workflows.
2. Orchestration: subagents/delegation, tool integrations, skills, multi-agent/session routing, central multi-channel gateway, channel/user routing, and deterministic Lobster-style pipelines.
3. Reach and extensibility: messaging integrations, event hooks, mobile device nodes, and gateway-centric management.
4. Learning and scale: agent-managed skill creation, evaluated skill improvement, cross-session full-text retrieval, programmatic tool calling (execute_code), batch processing and trajectory export, and Atropos RL-training integration.

These are target areas, not promised completion dates for every feature. Reorder them when measured dependencies, risk, or competition feedback justify it.

### January 2027: Demo review readiness
- Keep the primary workflow stable and reproducible.
- Verify installation, configuration, safety boundaries, and documentation from a clean environment.
- Prepare a short demo and supporting technical evidence.
- Confirm the official review date when announced.

## Quality gates for every change

A feature is not release-ready merely because it works once.

1. **Correctness:** targeted tests cover success, invalid input, and relevant edge cases.
2. **Regression:** the full test suite passes on the exact candidate commit.
3. **Security:** authorization, path boundaries, approval semantics, sandbox restrictions, and secret handling remain intact where applicable.
4. **Failure behavior:** timeouts, provider failures, interruption, and partial state are handled explicitly.
5. **Observability:** errors and outcomes are understandable without exposing secrets.
6. **Reproducibility:** documented commands can reproduce the behavior and its tests.
7. **Reviewability:** changes stay scoped, have a clear PR description, and are not merged until the repository owner approves.

If a quality gate fails, fix or revert the change instead of weakening the test or silently accepting the regression. Do not optimize speed or cost at the expense of correctness or safety.

## Competitive evaluation

Do not claim AETHER CLAW is more powerful than OpenClaw or Hermes Agent based on feature lists alone. Compare systems on the same representative tasks and report:
- task completion and verified test-pass rates,
- regression and recovery rates,
- security-boundary tests,
- latency and provider cost,
- setup/reproducibility and operator effort.

Use comparable task definitions and configurations. State test conditions and limitations; do not invent scores or imply a benchmark was run when it was not.

## Complete 24-capability roadmap

All requested capabilities remain in scope:

1. Browser Automation
2. Terminal & Command Execution
3. File Operations
4. Persistent Memory
5. Scheduled Tasks
6. Multi-step Workflow
7. Subagents & Task Delegation
8. Tools & Integrations
9. Messaging Integrations
10. Event Hooks
11. Skills System
12. Multi-agent / Session Routing
13. Central Multi-channel Gateway architecture
14. Mobile Device Nodes
15. Channel- and user-specific session routing
16. Lobster workflow pipelines
17. Gateway-centric assistant management
18. Agent-managed skill creation
19. Skill self-improvement
20. Cross-session full-text search and recall
21. Multiple Terminal Backends
22. Programmatic Tool Calling (execute_code)
23. Batch Processing and trajectory export
24. Atropos RL-training integration

Track each as **implemented**, **prototype**, **planned**, or **blocked**, backed by tests or reproducible evidence. Keep the roadmap intact while implementing in dependency order.
