# Day 1 Issues Log

## Issue 1: Model directory empty after git clone
**Symptom:** `/root/work/qlzhang/code/models/Qwen3-Coder-30B-A3B-Instruct/` only contained `.git`, no model files.
**Root Cause:** The repo was cloned with `git clone` but LFS files were not pulled. The repo had no commits on master (`your current branch 'master' does not have any commits yet`).
**Fix:** Deleted the broken clone and re-downloaded using `huggingface-cli download`.

## Issue 2: git lfs pull fails - "Can't resolve ref HEAD"
**Symptom:** `git lfs pull` failed with `Git can't resolve ref: "HEAD"`.
**Root Cause:** The git repo was in a broken state with an empty master branch and no commits.
**Fix:** Used `huggingface-cli download` instead of git lfs, which handles downloads more reliably.

## Issue 3: transformers version too old for Qwen3 MoE
**Symptom:** `ValueError: model type 'qwen3_moe' but Transformers does not recognize this architecture`
**Root Cause:** Installed transformers 4.48.2, but Qwen3 MoE requires >= 4.52.3.
**Fix:** `pip install --upgrade transformers` → upgraded to 4.57.6.
**Note:** This caused a dependency conflict with `chattts-fork` which requires `transformers~=4.41.1`.

## Issue 4: Parser didn't handle code block tool calls
**Symptom:** Model (Qwen2.5-7B) outputted tool calls inside markdown code blocks instead of `<tool_call>` XML tags:
```
I'll read the file for you.
\```python
{"tool": "Read", "parameters": {"file_path": "..."}}
\```
```
The parser only recognized XML-style `<tool_call>` tags, so the tool was never executed.
**Fix:** Updated `parser.py` to handle three formats:
1. XML tags: `<tool_call>...</tool_call>`
2. Code blocks: `` ```python ... ``` ``
3. Plain JSON with `"tool"` key

## Issue 5: `torch_dtype` deprecation warning
**Symptom:** `torch_dtype is deprecated! Use dtype instead!` warning during model loading.
**Root Cause:** `client.py` uses `torch_dtype=torch.bfloat16` which is deprecated in newer transformers.
**Status:** Fixed. Changed `torch_dtype` to `dtype` in `client.py`.

## Issue 6: Test 3 tool call not executed (Qwen3)
**Symptom:** In the Qwen3 test, Test 3 ("verify the fix") returned the raw tool call JSON instead of executing it:
```
Response: {"tool": "Read", "parameters": {"file_path": "..."}}
</tool_call>
```
**Root Cause:** The model outputted a malformed tool call - JSON followed by a closing `</tool_call>` tag without an opening tag. The parser couldn't match it.
**Status:** Open. Need more robust parsing or better system prompt to enforce consistent tool call format.

## Issue 7: No streaming output during generation
**Symptom:** After typing input, the REPL shows no progress while the model generates tokens. For the 30B model this can take 30+ seconds with no feedback, appearing frozen.
**Root Cause:** `model.generate()` was called without a streamer, so output only appeared after full generation completed.
**Fix:** Added `TextStreamer` to stream tokens to stdout in real-time during generation. Also changed `run()` to print directly instead of returning a string.

## Issue 8: Model acts like generic chatbot, not a coding agent
**Symptom:** When user says "read and analyze the buggy code", the model asks user to paste code or upload files instead of using tools to find and read files.
**Root Cause:** System prompt was too generic. It didn't tell the model about the working directory, didn't instruct it to proactively use tools (Bash/Read) to explore files, and didn't emphasize "never ask the user to paste code."
**Fix:** Rewrote system prompt to:
1. Include the working directory path
2. Instruct the model to ALWAYS use tools first (Bash to list files, Read to examine them)
3. Explicitly say "NEVER ask the user to paste code or upload files"
4. Provide a concrete example of proactive tool use (find → read → analyze)

## Issue 9: System prompt leaked into streamed output
**Symptom:** The full system prompt ("A: system\nYou are a coding agent...") was printed to the user during generation, making the output unreadable.
**Root Cause:** `TextStreamer` was printing ALL tokens including the input prompt. It does not have a reliable `skip_prompt` option.
**Fix:** Switched from `TextStreamer` to `TextIteratorStreamer` with `skip_prompt=True`. Generation runs in a background thread; the main thread iterates only over newly generated tokens and prints them.

## Issue 10: Model guesses file paths instead of discovering them
**Symptom:** When user says "Read buggy_code.py", model tries hardcoded paths like `/mvp/src/buggy_code.py` instead of searching. After "File not found", it guesses another wrong path instead of using `find`.
**Root Cause:** System prompt didn't instruct the model to use `find` for path discovery, and the example only showed a direct tool call without locating the file first.
**Fix:** Updated system prompt:
1. Added rule: "When a file path is unclear, use Bash(`find . -name 'filename'`) to locate it. NEVER guess paths."
2. Added rule: "For Read/Write tools, always use ABSOLUTE paths."
3. Changed the example to show the find-then-read pattern.
4. Inject a file tree snapshot into the system prompt at startup so the model always knows what files exist and where they are.

## Issue 11: Client only executes one round of tool calls
**Symptom:** Model does `find` → gets result → generates Read tool call → but Read never executes. The client stops after one tool round.
**Root Cause:** `run()` had a fixed two-step flow: generate → execute tools → generate final response → done. If the second generation also contained tool calls, they were ignored.
**Fix:** Changed `run()` to loop (up to 5 rounds): generate → if tool calls, execute and loop; if no tool calls, done. This supports multi-step workflows like find → read → analyze.
