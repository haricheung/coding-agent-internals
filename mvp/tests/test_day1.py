#!/usr/bin/env python3
"""
Quick test script for Day 1 functionality
Tests that the model can read a file, understand it, and identify bugs
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../src'))

from client import Client


def test_day1():
    """Test Day 1 success metric: read file, understand, write simple fix"""

    model_path = "/root/work/qlzhang/code/models/Qwen3-Coder-30B-A3B-Instruct"

    print("=== Day 1 Test ===")
    print("Testing: Model can read file, understand, and identify bugs\n")

    # Initialize client
    print("Initializing client...")
    client = Client(model_path)

    # Test 1: Read the buggy file
    print("\n--- Test 1: Read buggy file ---")
    response = client.run("Read the file /root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py")
    print(f"Response: {response[:200]}...")

    # Test 2: Identify the bug
    print("\n--- Test 2: Identify bug ---")
    response = client.run("What bug do you see in this code? Explain the issue.")
    print(f"Response: {response}")

    # Test 3: Write fixed version
    print("\n--- Test 3: Write fixed version ---")
    response = client.run("Write the corrected version to /root/work/qlzhang/code/coding-agent-internals/mvp/tests/fixed_code.py")
    print(f"Response: {response}")

    print("\n=== Day 1 Test Complete ===")
    print("Check if fixed_code.py was created and contains the correct fix")


if __name__ == "__main__":
    test_day1()
