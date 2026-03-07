# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Agent Team Mode

This project uses agent team mode. When working on tasks:
- Use TodoWrite to create and track task lists for multi-step work
- Spawn subagents via the Agent tool to parallelize independent work
- Coordinate between agents using the task system (TaskCreate, TaskUpdate, TaskList)
