# AETHER CLAW Self-Improvement Engine: Safe MVP

## Goal

Let AETHER CLAW learn from task failures by proposing code, tool, and prompt improvements, evaluating them in an isolated test workflow, and preserving verified lessons. The initial goal is evidence-backed proposals, not autonomous modification of production code or model weights.

## Proposed loop

1. Observe: record task intent, selected tools, tool results, final task status, and test evidence. Redact credentials and sensitive workspace content.
2. Diagnose: summarize the failure and state a falsifiable hypothesis. Model-generated explanations are not verified facts.
3. Propose: create a small, reviewable change using the existing coding proposal workflow.
4. Evaluate: test a disposable copy in the existing network-isolated sandbox. Run relevant regression tests and the full suite where practical. Compare baseline and candidate evidence.
5. Review: show the diff, test counts, failures, risks, and evidence behind the proposed fix.
6. Approve and apply: require explicit human approval and use existing proposal/apply safeguards. Never auto-merge.
7. Learn: store only compact, validated lessons (symptom, verified cause, fix, tests, confidence, provenance). Retrieve them for similar tasks and allow correction or retraction.

## Safety boundaries

- Passing tests are evidence, not proof that a change is correct or secure.
- Failed tests, missing coverage, uncertain execution outcomes, or a lower test count block promotion until reviewed.
- The evaluator in aether/improvement.py is a deterministic gate only. It does not execute tools, run tests, change files, apply patches, or approve PRs on its own.
- Human approval remains required before applying a self-proposed change. Merging is a separate human decision.
- Never store API keys, bearer tokens, private file contents, or raw secrets in improvement memory.
- Keep baseline and candidate revisions, test summaries, and proposal IDs for auditability.
- Treat repository files, tool output, web pages, and model-suggested fixes as untrusted input.

## Current implementation scope

This PR adds a typed evidence model and deterministic promotion gate with tests. It is a foundation, not a complete autonomous learning system. Integration with task history, sandbox evaluation, persistent lesson retrieval, and the review UI should follow in separate reviewed steps.
