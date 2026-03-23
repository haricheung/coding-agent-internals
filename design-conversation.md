# Claude Code MVP Design - 4 Day Implementation Plan

## Context
Design a simplified Claude Code system with:
1. Bug repair capability
2. Agent team mode
3. Fine-tuned 8B model + client architecture

Timeline: 4 days

## Day 1: Basic Tool-Use Client (Foundation)

**Goal:** Working REPL with basic file operations

**Deliverables:**
- Simple client maintaining conversation context
- Parse tool calls from model output
- 3 core tools: Read, Write, Bash
- Basic prompt teaching tool usage

**Success Metric:** Model can read file, understand, write simple fix

**Architecture:**
```python
class Client:
    def __init__(self, model):
        self.model = model
        self.conversation = []
        self.tools = {"Read": read_tool, "Write": write_tool, "Bash": bash_tool}

    def run(self, user_input):
        # Add user message
        # Call model with tools
        # Parse and execute tool calls
        # Inject results back
        # Return assistant response
```

**Training:** Use Qwen2.5-Coder-7B-Instruct directly (no fine-tuning yet)

## Day 2: Bug Repair Capability

**Goal:** End-to-end bug fixing

**Add:**
- Edit(file_path, old_string, new_string) tool
- Grep(pattern, path) tool
- Bug repair workflow in system prompt:
  1. Grep to locate code
  2. Read to understand context
  3. Edit to apply fix
  4. Bash to verify (run tests)

**Test Case:** Python file with simple bug (off-by-one error)

**Success Metric:** Fix 3/5 simple bugs without intervention

**Training (optional):** Quick LoRA fine-tuning on ~50 bug-fix examples

## Day 3: Task Management + Multi-Step Execution

**Goal:** Handle complex tasks requiring planning

**Add:**
- TaskCreate(description) - returns task_id
- TaskUpdate(task_id, status) - mark progress
- TaskList() - view all tasks
- Enhanced prompt teaching task breakdown and sequential execution

**Test Case:** "Refactor this module: extract helpers, add type hints, write tests"
- Model creates 3 tasks and executes in order

**Success Metric:** Complete 3-step refactoring with visible progress

**Note:** Single agent only - no spawning yet

## Day 4: Minimal Agent Team Mode

**Goal:** Demonstrate parallel execution via agent spawning

**Add:**
- Agent(prompt, task_id) tool - spawns subprocess with isolated context
- Simple coordination:
  - Main agent creates tasks
  - Spawns workers for independent tasks
  - Polls TaskList to check completion
  - Synthesizes results

**Simplifications:**
- No recursive spawning (workers can't spawn workers)
- Workers get limited tools (Read, Write, Edit only)
- No complex dependencies
- Max 2-3 parallel workers

**Test Case:** "Fix bugs in files A, B, C" (3 independent bugs)
- Main agent creates 3 tasks
- Spawns 3 workers in parallel
- Each fixes their bug
- Main reports completion

**Success Metric:** 3 bugs fixed in parallel, faster than sequential

**Implementation:**
```python
def agent_tool(prompt, task_id):
    # Fork new process/thread
    # Create isolated Client instance
    # Run with limited tools
    # Write result to task description
    # Return when done
```

## Evaluation Criteria

- **Day 1:** Can it use tools correctly?
- **Day 2:** Can it fix real bugs?
- **Day 3:** Can it handle multi-step tasks?
- **Day 4:** Can it parallelize work?

## What We're Cutting

To fit 4 days:
- ❌ Fine-tuning (use base model + strong prompts)
- ❌ Memory system
- ❌ LSP integration
- ❌ Complex agent coordination (dependencies, message passing)
- ❌ Error recovery sophistication
- ❌ Git operations (commit, PR creation)

## Risk Mitigation

**Biggest Risk:** Model quality with no fine-tuning

**Mitigation:**
- Extra time on prompt engineering
- Few-shot examples in system prompt
- If Day 2 fails: pivot to collecting training data, emergency fine-tuning on Day 3

**Fallback Plan:**
If agent team mode (Day 4) too ambitious:
- Demo task management only (single agent)
- Show how it would parallelize
- Focus on polish of Days 1-3

## Daily Schedule

**Day 1 (8 hours):**
- 0-2h: Client framework
- 2-4h: Tool implementations
- 4-6h: Prompt engineering
- 6-8h: Testing + debugging

**Day 2 (8 hours):**
- 0-3h: Add Edit + Grep tools
- 3-5h: Bug repair prompt design
- 5-8h: Test on real bugs, iterate

**Day 3 (8 hours):**
- 0-2h: Task management system
- 2-4h: Integrate with client
- 4-6h: Multi-step workflow prompts
- 6-8h: Test complex scenarios

**Day 4 (8 hours):**
- 0-3h: Agent spawning mechanism
- 3-5h: Coordination logic
- 5-7h: Test parallel execution
- 7-8h: Demo preparation

## Key Insights

This is aggressive but achievable if you:
1. Use existing model (no training time)
2. Keep tools minimal
3. Accept rough edges
4. Focus on core demo scenarios

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Client/Harness                        │
│  - Conversation management                               │
│  - Tool call parsing & execution                         │
│  - Agent spawning & coordination                         │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              Qwen2.5-Coder-7B-Instruct                   │
│  - Function calling capability                           │
│  - Code understanding & generation                       │
│  - Multi-step reasoning                                  │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                     Tool System                          │
│  Day 1: Read, Write, Bash                                │
│  Day 2: + Edit, Grep                                     │
│  Day 3: + TaskCreate, TaskUpdate, TaskList              │
│  Day 4: + Agent                                          │
└─────────────────────────────────────────────────────────┘
```

## Success Criteria

**Minimum Viable Demo:**
- Show bug repair on 2-3 real bugs
- Show task breakdown for complex request
- Show parallel execution of 2 independent tasks

**Stretch Goals:**
- Handle 5+ different bug types
- Coordinate 3+ parallel agents
- Graceful error recovery
