#!/usr/bin/env python3
"""
Main entry point for the Claude Code MVP
Simple REPL interface for Day 1
"""

import os
import sys
import argparse
from client import Client


def main():
    """Run the REPL"""
    parser = argparse.ArgumentParser(description="Claude Code MVP - Day 1 REPL")
    parser.add_argument("--server", default="http://localhost:9981",
                        help="Model server URL (default: http://localhost:9981)")
    parser.add_argument("--trace", action="store_true",
                        help="Enable trajectory logging (dim [TRACE] lines)")
    parser.add_argument("working_dir", nargs="?", default=os.getcwd(),
                        help="Working directory for the agent (default: cwd)")
    args = parser.parse_args()

    if args.trace:
        import trajectory
        trajectory.enable()

    working_dir = os.path.abspath(args.working_dir)

    try:
        client = Client(server_url=args.server, working_dir=working_dir)
    except ConnectionError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"\n=== Claude Code MVP ===")
    print(f"Working dir: {working_dir}")
    print("Type 'exit' to quit, 'reset' to clear conversation\n")

    while True:
        try:
            user_input = input("🧑 You: ").strip()

            if not user_input:
                continue

            if user_input.lower() == 'exit':
                print("👋 Goodbye!")
                break

            if user_input.lower() == 'reset':
                client.reset()
                print("🔄 Conversation reset.")
                continue

            client.run(user_input)
            print()  # newline after streamed response

        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
