import pytest
from aether.improvement import ImprovementProposal, TestEvidence, evaluate_improvement

def test_proposal_requires_a_concrete_description():
    with pytest.raises(ValueError, match="title must not be empty"):
        ImprovementProposal("", "tool failed", "better routing", "change prompt")

def test_candidate_that_fails_tests_is_blocked():
    result = evaluate_improvement(TestEvidence(True, 235), TestEvidence(False, 236, 1))
    assert result.status == "blocked"
    assert not result.eligible_for_review
    assert any("Candidate tests must pass" in reason for reason in result.reasons)

def test_candidate_with_missing_tests_is_blocked():
    result = evaluate_improvement(TestEvidence(True, 235), TestEvidence(True, 234))
    assert result.status == "blocked"
    assert any("test count is lower" in reason for reason in result.reasons)

def test_passing_candidate_requires_human_approval():
    baseline = TestEvidence(True, 235)
    candidate = TestEvidence(True, 236)
    review = evaluate_improvement(baseline, candidate)
    assert review.status == "ready_for_review"
    assert review.eligible_for_review
    approved = evaluate_improvement(baseline, candidate, human_approved=True)
    assert approved.status == "approved_for_apply"

def test_invalid_test_evidence_is_rejected():
    with pytest.raises(ValueError, match="0 <= failed <= total"):
        TestEvidence(False, 2, 3)
