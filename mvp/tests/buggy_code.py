"""
A simple Python file with a bug for testing Day 1
"""

def calculate_sum(numbers):
    """Calculate the sum of a list of numbers"""
    total = 0
    for i in range(len(numbers)):
        total += numbers[i + 1]  # Bug: off-by-one error
    return total


def main():
    nums = [1, 2, 3, 4, 5]
    result = calculate_sum(nums)
    print(f"Sum: {result}")


if __name__ == "__main__":
    main()
