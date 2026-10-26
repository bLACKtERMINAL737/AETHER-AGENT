# AETHER CLAW — Feature Parity & Verification Roadmap

This is a tracked implementation plan inspired by the user-provided Hermes Agent feature inventory. It is not a claim that these features already exist. Each item must be audited against code, implemented where missing, and verified with repeatable tests before being marked complete.

## Status legend
- `AUDIT`: inspect current implementation and tests.
- `PLANNED`: missing or partial; design and implement.
- `IMPLEMENTED`: code exists; still requires verification.
- `VERIFIED`: implementation and documented test evidence pass.
- `BLOCKED`: requires credentials, external service, hardware, or a deliberate scope decision.

## Safety and delivery rules
1. Work in small, reviewable feature batches on feature branches.
2. Add tests with each capability; run focused tests and the full suite.
3. Never claim a feature is verified solely because an endpoint, UI control, or configuration option exists.
4. External integrations remain optional and disabled until configured.
5. Preserve local-first operation, least privilege, secret redaction, sandboxing, audit logs, and explicit approval for risky changes.
6. Never autonomously retrain models or apply self-generated code/skills without validation and user-controlled approval.
7. Open PRs for review; do not merge without explicit user approval.
8. Features that need real credentials or interactive local hardware must be marked BLOCKED until the user runs the integration test.

## A. Core AI and reasoning
| ID | Feature | Initial status | Verification target |
|---:|---|---|---|
| 1 | Coding and terminal automation | AUDIT | Safe workspace file operations, command allowlist/sandbox, coding and debugging E2E tests |
| 2 | Browser automation | PLANNED | Browser backend abstraction, navigation/actions, isolated session and interaction tests |
| 3 | Persistent memory and learning | AUDIT | Explicit memory CRUD/retrieval; skill/workflow learning separately tested and approved |
| 4 | Scheduled automation | PLANNED | Durable scheduler, timezone/retry semantics, pause/resume and delivery tests |
| 5 | Multi-agent delegation | PLANNED | Role-based agents, task registry, bounded parallelism, cancellation and result review |
| 6 | Model provider support | AUDIT | Provider contract tests, configuration validation, secret-safe route discovery |
| 7 | Task planning and todo | AUDIT | Task decomposition, dependency tracking, status transitions and recovery tests |
| 8 | Clarification | PLANNED | Ask when requirements are materially ambiguous; test against unnecessary questions |
| 9 | Smart routing and fallback | AUDIT | Route selection, transient-failure fallback, no secret leakage and deterministic tests |
| 10 | Session management and recall | AUDIT | Session history, search, boundaries, persistence and access-control tests |

## B. Memory, skills and context
| ID | Feature | Initial status | Verification target |
|---:|---|---|---|
| 11 | Persistent memory files / user memory | AUDIT | Structured memory, explicit write/delete, relevance and privacy tests |
| 12 | Skills system | PLANNED | Versioned skill format, discover/load, provenance and sandboxed execution |
| 13 | Skill creation and improvement | PLANNED | Generate proposals, test/evaluate, human approval, rollback and audit trail |
| 14 | Context files (AGENTS.md, SOUL.md etc.) | PLANNED | Defined precedence, safe parsing, path limits and prompt-injection tests |
| 15 | Context references (@file/folder/diff/URL) | PLANNED | Explicit reference resolution, size limits, URL policy and permission tests |

## C. Coding, terminal and files
| ID | Feature | Initial status | Verification target |
|---:|---|---|---|
| 16 | Terminal execution | PLANNED | Explicit command policy, timeout/output limits, sandbox and audit log |
| 17 | File reading | AUDIT | Workspace boundary, symlink/path traversal and size/encoding tests |
| 18 | File editing and patching | AUDIT | Diff-first proposals, stale-file protection, explicit approval and rollback |
| 19 | Process management | PLANNED | Start/status/stop, timeout, output capture, cleanup and ownership tests |
| 20 | Code execution | PLANNED | Isolated runtime, resource limits, no network by default and language policy |
| 21 | Checkpoints and rollback | PLANNED | Atomic snapshots, integrity verification, restore tests and retention policy |
| 22 | Git-aware workflow | PLANNED | Status/diff/branch awareness, no destructive Git actions without approval |
| 23 | Testing and debugging | AUDIT | Disposable workspace, bounded fix rounds, reproducible logs and regression tests |
| 24 | Remote execution (SSH/container/cloud) | PLANNED | Optional backend, explicit host allowlist, credential isolation and audit trail |

## D. Web research and browser control
| ID | Feature | Initial status | Verification target |
|---:|---|---|---|
| 25 | Web search | AUDIT | Tool contract, source URLs, timeouts and search-result tests |
| 26 | Web extraction | PLANNED | Main-content extraction, size limits, hostile-page handling and attribution |
| 27 | Browser navigation | PLANNED | Browser lifecycle, navigation policy, session isolation and tests |
| 28 | Browser interaction | PLANNED | Click/type/form allowlists, confirmation for consequential actions |
| 29 | Browser vision | PLANNED | Screenshot capture and vision-capable provider integration tests |
| 30 | Research synthesis | PLANNED | Multi-source evidence, citations, uncertainty and contradiction tests |
| 31 | X/Twitter search | BLOCKED | Optional provider/credentials; verify only when configured |

## E. Image, vision and voice
| ID | Feature | Initial status | Verification target |
|---:|---|---|---|
| 32 | Vision analysis | PLANNED | Image input validation, supported model routing and image test fixtures |
| 33 | Image generation | PLANNED | Optional provider adapter, output validation, cost/error handling |
| 34 | Voice mode | PLANNED | Optional audio input/output loop, permissions and device integration test |
| 35 | Text-to-speech | PLANNED | Provider abstraction, supported languages, cancellation and failure tests |
| 36 | Voice transcription | PLANNED | Provider abstraction, file limits, privacy and transcript tests |
| 37 | Wake word | BLOCKED | Optional local runtime/device dependency; opt-in, CPU/privacy tests |

## F. Automation and autonomous execution
| ID | Feature | Initial status | Verification target |
|---:|---|---|---|
| 38 | Cron scheduling | PLANNED | Durable scheduler, restart recovery and timezone tests |
| 39 | Natural-language scheduling | PLANNED | Parse/confirm schedule; timezone and ambiguity tests |
| 40 | Scheduled delivery | PLANNED | Channel adapter, retries, idempotency and delivery receipts |
| 41 | Job management | PLANNED | List/edit/pause/resume/remove with authorization and audit tests |
| 42 | Subagent delegation | PLANNED | Specialist registry, bounded delegation, result aggregation and tests |
| 43 | Parallel execution | PLANNED | Concurrency caps, cancellation, failure isolation and resource limits |
| 44 | Programmatic tool calling | AUDIT | Strict schemas, call limits, validation, error recovery and tracing |
| 45 | Event hooks | PLANNED | Typed lifecycle events, timeout, isolation and recursion protection |
| 46 | Webhooks and notifications | PLANNED | Signed inbound hooks, outbound retries, secret redaction and SSRF protection |

## G. Messaging and multi-bot
| ID | Feature | Initial status | Verification target |
|---:|---|---|---|
| 47 | Messaging gateway | PLANNED | Channel-neutral adapter, authentication and message routing tests |
| 48 | Direct messaging | PLANNED | User/channel identity mapping and authorization tests |
| 49 | Group chat integration | PLANNED | Mention rules, access control and privacy tests |
| 50 | Voice in messaging | PLANNED | Channel capability negotiation and media tests |
| 51 | Named bot mode | PLANNED | Per-bot identity, model, tools and isolated memory |
| 52 | Specialist bots | PLANNED | Per-role policy and tool permissions with contract tests |
| 53 | Bot collaboration | PLANNED | Authenticated messages, task ownership, loops prevention and audit logs |

## H. External tools, MCP and plugins
| ID | Feature | Initial status | Verification target |
|---:|---|---|---|
| 54 | MCP integration | PLANNED | Client lifecycle, schema validation, timeout and permission tests |
| 55 | MCP tool filtering | PLANNED | Allowlist/denylist enforcement and prompt-injection tests |
| 56 | Custom plugins | PLANNED | Versioned plugin API, trust boundaries, lifecycle and compatibility tests |
| 57 | Memory-provider plugins | PLANNED | Adapter contract, migrations, privacy and retrieval parity tests |
| 58 | Context-engine plugins | PLANNED | Adapter contract, bounded context and deterministic tests |
| 59 | Home Assistant integration | BLOCKED | Optional credentials/device setup; scoped commands and confirmation tests |
| 60 | Custom API integration | PLANNED | OpenAPI/schema adapter, credential isolation, timeout and SSRF tests |

## I. Advanced developer and research
| ID | Feature | Initial status | Verification target |
|---:|---|---|---|
| 61 | OpenAI-compatible API server | AUDIT | API compatibility, auth, streaming/error semantics and contract tests |
| 62 | IDE integration / ACP | PLANNED | Optional protocol adapter, capability negotiation and editor integration test |
| 63 | Batch processing | PLANNED | Bounded concurrency, resumability, per-item errors and cost controls |
| 64 | Trajectory export | PLANNED | Redacted structured export, schema versioning and privacy tests |
| 65 | Evaluation and training workflows | PLANNED | Evaluation harness and datasets; training is a separate opt-in project |
| 66 | Atropos/RL research integration | BLOCKED | Separate research environment, explicit datasets/compute and safety review |
| 67 | Prompt caching | PLANNED | Provider capability detection and correctness/cost measurements |
| 68 | Credential pools | PLANNED | Secure secret-store integration, rotation, redaction and failure tests |
| 69 | Provider fallback | AUDIT | Failure classification, retry limits, no retry on unsafe/non-transient errors |
| 70 | Fine-grained provider routing | AUDIT | Task policy, capability checks, route telemetry and deterministic tests |

## J. Personalization and user experience
| ID | Feature | Initial status | Verification target |
|---:|---|---|---|
| 71 | Personality customization | PLANNED | Versioned preferences with safety/system policy precedence |
| 72 | SOUL.md identity file | PLANNED | Explicit parsing, precedence and untrusted-content tests |
| 73 | Personality presets | PLANNED | Preset validation and session-scoped behavior tests |
| 74 | CLI customization | PLANNED | Accessible configuration, no secret display and CLI smoke tests |
| 75 | Session-specific toolsets | PLANNED | Tool allowlists per session and enforcement tests |
| 76 | Setup profiles | PLANNED | Minimal/full/custom profiles, validation and repeatable setup tests |
| 77 | Desktop app | BLOCKED | Separate packaging/UI project, signed build and platform smoke tests |

## Implementation sequence
1. **Phase 0 — Baseline audit:** inspect default branch and existing tests; map current code to every ID; identify gaps without overwriting local work.
2. **Phase 1 — Reliability and safety:** finish coding E2E verification, command/tool permission model, checkpoint/rollback, audit logs and regression tests.
3. **Phase 2 — Agent orchestration:** planner, task registry, specialist subagents, bounded parallelism, cancellation and review gates.
4. **Phase 3 — Tools:** terminal/process tools, Git workflow, web search/extraction, browser backend and MCP/plugin interfaces.
5. **Phase 4 — Memory and skills:** context files/references, skill versioning, skill proposals/evaluation and retrieval quality.
6. **Phase 5 — Automation and integrations:** scheduler, hooks, notifications, messaging, named bots and external services.
7. **Phase 6 — Multimodal and advanced research:** vision, image, voice, ACP, batch/trajectory/evaluation and optional RL.
8. **Phase 7 — UX and packaging:** personality profiles, CLI, setup profiles, desktop app.
9. **Release gates:** focused tests, full test suite, static/security checks, documented manual integration tests, review PR, user approval before merge.

## Evidence log
Append dated entries for each verified feature batch with commit/PR link, test commands, pass counts, manual checks and known limitations. Do not change an item to VERIFIED without evidence.
