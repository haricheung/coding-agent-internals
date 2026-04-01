"""
Test suite for buggy_calc.py (Demo 3 / Lecture 3).

These tests are designed so that:
  - test_average fails first (bug 1: wrong divisor)
  - After fixing bug 1, test_pass_rate still fails (bug 2: boundary error)
  - After fixing bug 2, all tests pass

This two-stage failure pattern demonstrates the Orient moment:
  the agent must understand a NEW error after fixing the first bug.
"""

from buggy_calc import stats_report


def test_average():
    """Average of [80, 60, 90, 70, 50] should be 70.0"""
    scores = [80, 60, 90, 70, 50]
    result = stats_report(scores)
    assert result["average"] == 70.0, (
        f"Expected average 70.0, got {result['average']}"
    )


def test_pass_rate():
    """4 out of 5 scores >= 60 (80, 60, 90, 70), so pass rate = 80.0%"""
    scores = [80, 60, 90, 70, 50]
    result = stats_report(scores)
    assert result["pass_rate"] == 80.0, (
        f"Expected pass_rate 80.0%, got {result['pass_rate']}%"
    )


def test_highest():
    scores = [80, 60, 90, 70, 50]
    result = stats_report(scores)
    assert result["highest"] == 90


def test_lowest():
    scores = [80, 60, 90, 70, 50]
    result = stats_report(scores)
    assert result["lowest"] == 50


def test_all_pass():
    """All scores >= 60 should give 100% pass rate"""
    scores = [100, 80, 60]
    result = stats_report(scores)
    assert result["pass_rate"] == 100.0
    assert result["average"] == 80.0


def test_none_pass():
    """All scores < 60 should give 0% pass rate"""
    scores = [50, 40, 30]
    result = stats_report(scores)
    assert result["pass_rate"] == 0.0
