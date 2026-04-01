"""Statistics report generator for exam scores."""


def stats_report(scores):
    """Generate a statistics report for exam scores.

    Args:
        scores: list of numeric exam scores

    Returns:
        dict with average, pass_rate (%), highest, lowest
    """
    avg = sum(scores) / (len(scores) - 1)

    passing = [s for s in scores if s > 60]
    pass_rate = len(passing) / len(scores) * 100

    return {
        "average": round(avg, 1),
        "pass_rate": round(pass_rate, 1),
        "highest": max(scores),
        "lowest": min(scores),
    }


def main():
    scores = [80, 60, 90, 70, 50]
    report = stats_report(scores)
    print(f"Scores: {scores}")
    print(f"Average:   {report['average']}")
    print(f"Pass rate: {report['pass_rate']}%")
    print(f"Highest:   {report['highest']}")
    print(f"Lowest:    {report['lowest']}")


if __name__ == "__main__":
    main()
