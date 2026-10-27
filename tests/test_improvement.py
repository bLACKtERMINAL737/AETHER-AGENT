import pytest
from aether.improvement import ImprovementProposal, TestEvidence, evaluate_improvement, parse_pytest_evidence

def test_proposal_requires_a_concrete_description():
    with pytest.raises(ValueError, match="title must not be empty"):
        ImprovementProposal("", "tool failed", "better routing", "change prompt")

def test_candidate_that_fails_tests_is_blocked():
    result = evaluate_improvement(TestEvidence(True, 235), TestEvidence(False, 236, 1))
    assert result.status == "blocked"
    assert not result.eligible_for_review

def test_candidate_with_missing_tests_is_blocked():
    result = evaluate_improvement(TestEvidence(True, 235), TestEvidence(True, 234))
    assert result.status == "blocked"

def test_passing_candidate_requires_human_approval():
    baseline, candidate = TestEvidence(True, 235), TestEvidence(True, 236)
    assert evaluate_improvement(baseline, candidate).status == "ready_for_review"
    assert evaluate_improvement(baseline, candidate, human_approved=True).status == "approved_for_apply"

def test_invalid_test_evidence_is_rejected():
    with pytest.raises(ValueError, match="0 <= failed <= total"):
        TestEvidence(False, 2, 3)

def test_parse_pytest_evidence_passed_summary():
    result = {"passed": True, "stdout": "===== 33 passed in 0.21s ====="}
    assert parse_pytest_evidence(result) == TestEvidence(True, 33, 0)

def test_parse_pytest_evidence_counts_skips_and_failures():
    result = {"passed": False, "stdout": "===== 2 failed, 8 passed, 1 skipped in 1.2s ====="}
    assert parse_pytest_evidence(result) == TestEvidence(False, 11, 2)

def test_parse_pytest_evidence_fails_closed_on_missing_summary():
    assert parse_pytest_evidence({"passed": True, "stdout": "all good"}) is None

def test_parse_pytest_evidence_fails_closed_on_timeout():
    assert parse_pytest_evidence({"passed": False, "timed_out": True, "stdout": ""}) is None

def test_parse_pytest_evidence_fails_closed_when_all_tests_are_skipped():
    result = {"passed": True, "stdout": "===== 5 skipped in 0.01s ====="}
    assert parse_pytest_evidence(result) is None

def test_parse_pytest_evidence_fails_closed_when_no_tests_pass():
    result = {"passed": True, "stdout": "===== 3 xfailed in 0.01s ====="}
    assert parse_pytest_evidence(result) is None
