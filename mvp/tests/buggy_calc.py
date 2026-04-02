"""Statistics report generator for exam scores."""


def stats_report(scores):
    """Generate a statistics report for exam scores.

    Args:
        scores: list of numeric exam scores

    Returns:
        dict with average, std_dev, median, pass_rate (%), highest, lowest
    """
    n = len(scores)
    avg = sum(scores) / n

    # Standard deviation
    variance = sum((s - avg) ** 2 for s in scores) / n
    std_dev = variance ** 0.5

    # Median
    sorted_scores = sorted(scores)
    mid = n // 2
    if n % 2 == 0:
        median = sorted_scores[mid]
    else:
        median = sorted_scores[mid]

    # Pass rate (>= 60 is passing)
    passing = [s for s in scores if s >= 60]
    pass_rate = len(passing) / n * 100

    return {
        "average": round(avg, 1),
        "std_dev": round(std_dev, 1),
        "median": round(median, 1),
        "pass_rate": round(pass_rate, 1),
        "highest": max(scores),
        "lowest": min(scores),
    }


def main():
    scores = [80, 60, 90, 70, 50, 100]
    report = stats_report(scores)
    for k, v in report.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
