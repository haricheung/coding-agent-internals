#!/usr/bin/env python3
"""
Main entry point for the Claude Code MVP
REPL with input history and CJK support (via prompt_toolkit)
"""

import os
import sys
import argparse
from client import Client

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory


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

    # History file: saved per working directory
    history_dir = os.path.join(working_dir, ".agent")
    os.makedirs(history_dir, exist_ok=True)
    history_file = os.path.join(history_dir, "history")

    session = PromptSession(history=FileHistory(history_file))

    print(f"\n=== Claude Code MVP ===")
    print(f"Working dir: {working_dir}")
    print("Type 'exit' to quit, 'reset' to clear conversation\n")

    while True:
        try:
            user_input = session.prompt("🧑 You: ").strip()

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
        except EOFError:
            print("\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
