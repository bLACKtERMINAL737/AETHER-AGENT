"""Safety gates for proposed self-improvements.

This module evaluates proposals only. It does not modify the workspace, run
arbitrary commands, or apply patches; guarded execution remains separate.
"""
from dataclasses import dataclass
from typing import Literal

GateStatus = Literal["blocked", "ready_for_review", "approved_for_apply"]

@dataclass(frozen=True)
class TestEvidence:
    """Auditable test evidence for one version of the workspace."""
    passed: bool
    total: int
    failed: int = 0

    def __post_init__(self) -> None:
        if self.total < 0 or self.failed < 0 or self.failed > self.total:
            raise ValueError("Test counts must satisfy 0 <= failed <= total")
        if self.passed and self.failed:
            raise ValueError("Passing evidence cannot contain failed tests")
        if not self.passed and self.failed == 0:
            raise ValueError("Failing evidence must report at least one failed test")

@dataclass(frozen=True)
class ImprovementProposal:
    """A candidate improvement with evidence, not an executable patch."""
    title: str
    observed_failure: str
    hypothesis: str
    patch_summary: str

    def __post_init__(self) -> None:
        for name in ("title", "observed_failure", "hypothesis", "patch_summary"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")

@dataclass(frozen=True)
class ImprovementEvaluation:
    """Result of comparing baseline and candidate test evidence."""
    status: GateStatus
    reasons: tuple[str, ...]
    baseline_tests: TestEvidence
    candidate_tests: TestEvidence

    @property
    def eligible_for_review(self) -> bool:
        return self.status in ("ready_for_review", "approved_for_apply")

def evaluate_improvement(baseline: TestEvidence, candidate: TestEvidence, *, human_approved: bool = False) -> ImprovementEvaluation:
    """Evaluate evidence; never applies changes or treats tests as full proof."""
    reasons: list[str] = []
    if not baseline.passed:
        reasons.append("Baseline tests must pass before comparing an improvement.")
    if not candidate.passed:
        reasons.append("Candidate tests must pass.")
    if candidate.total < baseline.total:
        reasons.append("Candidate test count is lower than baseline; investigate missing tests.")
    if reasons:
        return ImprovementEvaluation("blocked", tuple(reasons), baseline, candidate)
    if not human_approved:
        return ImprovementEvaluation("ready_for_review", ("Evidence passed; human review and approval are still required.",), baseline, candidate)
    return ImprovementEvaluation("approved_for_apply", ("Explicit approval recorded; use the existing guarded proposal workflow to apply.",), baseline, candidate)
