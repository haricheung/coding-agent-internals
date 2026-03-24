#!/usr/bin/env python3
"""
Test Day 1 MVP with Qwen3-Coder-30B-A3B-Instruct
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../src'))

from client import Client


def test_qwen3():
    """Test with Qwen3 model"""

    model_path = "/root/work/qlzhang/code/models/Qwen3-Coder-30B-A3B-Instruct"

    print("="*60)
    print("Day 1 MVP - Qwen3-Coder-30B-A3B-Instruct Test")
    print("="*60)
    print()

    # Initialize client
    print("Initializing client with Qwen3-Coder-30B-A3B-Instruct...")
    print("(This is a 30B MoE model, loading may take a minute...)")
    client = Client(model_path)
    print()

    # Test 1: Read buggy file
    print("Test 1: Read buggy_code.py")
    print("-" * 60)
    response = client.run("Read the file /root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py")
    print(f"Response: {response}\n")

    # Test 2: Identify and fix bug
    print("Test 2: Identify bug and write fix")
    print("-" * 60)
    response = client.run("What's the bug in this code? Write the corrected version to /root/work/qlzhang/code/coding-agent-internals/mvp/tests/fixed_code.py")
    print(f"Response: {response}\n")

    # Test 3: Verify the fix
    print("Test 3: Verify the fix was written")
    print("-" * 60)
    response = client.run("Read /root/work/qlzhang/code/coding-agent-internals/mvp/tests/fixed_code.py to verify it's correct")
    print(f"Response: {response}\n")

    print("="*60)
    print("Test complete!")
    print("="*60)


if __name__ == "__main__":
    try:
        test_qwen3()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
