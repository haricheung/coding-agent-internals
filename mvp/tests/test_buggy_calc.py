"""Tests for buggy_calc.py stats_report function."""
from buggy_calc import stats_report


def test_average():
    """Average of [80, 60, 90, 70, 50, 100] should be 75.0"""
    scores = [80, 60, 90, 70, 50, 100]
    result = stats_report(scores)
    assert result["average"] == 75.0, \
        f"Expected average 75.0, got {result['average']}"


def test_std_dev():
    """Sample standard deviation (divide by n-1, not n)"""
    scores = [80, 60, 90, 70, 50, 100]
    result = stats_report(scores)
    assert result["std_dev"] == 18.7, \
        f"Expected std_dev 18.7, got {result['std_dev']}"


def test_median_even():
    """Median of even-length list = average of two middle values"""
    scores = [80, 60, 90, 70, 50, 100]
    result = stats_report(scores)
    assert result["median"] == 75.0, \
        f"Expected median 75.0, got {result['median']}"


def test_median_odd():
    """Median of odd-length list = middle value"""
    scores = [80, 60, 90, 70, 50]
    result = stats_report(scores)
    assert result["median"] == 70.0, \
        f"Expected median 70.0, got {result['median']}"


def test_pass_rate():
    """Pass rate: scores >= 60 count as passing"""
    scores = [80, 60, 90, 70, 50, 100]
    result = stats_report(scores)
    assert result["pass_rate"] == 83.3, \
        f"Expected pass_rate 83.3%, got {result['pass_rate']}%"


def test_highest_lowest():
    """Highest and lowest scores"""
    scores = [80, 60, 90, 70, 50, 100]
    result = stats_report(scores)
    assert result["highest"] == 100
    assert result["lowest"] == 50
