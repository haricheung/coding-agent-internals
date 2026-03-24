#!/usr/bin/env python3
"""
Simple interactive test for Day 1 MVP
Tests basic tool usage with the Qwen model
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../src'))

from client import Client


def test_basic_interaction():
    """Test basic interaction with the model"""

    model_path = "/root/work/qlzhang/code/models/Qwen2.5-Coder-7B-Instruct"

    print("="*60)
    print("Day 1 MVP - Basic Interaction Test")
    print("="*60)
    print()

    # Initialize client
    print("Initializing client with Qwen2.5-Coder-7B-Instruct...")
    client = Client(model_path)
    print()

    # Test 1: Simple greeting
    print("Test 1: Simple greeting")
    print("-" * 40)
    response = client.run("Hello! Can you help me with code?")
    print(f"Response: {response}\n")

    # Test 2: Read a file
    print("Test 2: Read buggy_code.py")
    print("-" * 40)
    response = client.run("Please read the file /root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py")
    print(f"Response: {response}\n")

    # Test 3: Identify the bug
    print("Test 3: Identify the bug")
    print("-" * 40)
    response = client.run("What bug do you see in the code? Explain the issue briefly.")
    print(f"Response: {response}\n")

    print("="*60)
    print("Test complete!")
    print("="*60)


if __name__ == "__main__":
    try:
        test_basic_interaction()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
