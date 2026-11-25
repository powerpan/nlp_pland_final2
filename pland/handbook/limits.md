# Limits and guardrails of a run

- **Steps**: a run may take `max_iterations` model calls (default 80). At 80% there is a checkpoint; if the files a
  delegator asked for do not exist yet, the next steps offer only file-writing tools. At the limit you are asked
  to summarise what is done and what is not.
- **Run budget**: each top-level run owns a budget of `max_run_calls` model calls (default 300) and
  `max_run_tokens` weighted tokens (default 8,000,000; a cached input token counts 0.1). Everything it delegates
  shares that budget; a group drive gets twice as much. At 70% the root agent is told what is left; at 90%
  non-root agents stop and new delegations are refused, keeping the last 10% for the root's summary. Each
  delegation and message result reports the current usage.
- **Loops**: the same tool with the same arguments is warned about at 3 repeats and stopped at 5; several
  consecutive results identical to earlier ones (no progress) end the run with a forced report.
- **Output**: one reply may produce up to `model.max_tokens` tokens (default 32,768, thinking included). A tool
  call cut off mid-way is not executed — write large files in parts (`write_file` with `append=true`).
- **Tool results** are capped at 24,000 characters (head and tail kept); `read_file` pages at about 20,000
  characters and says where to continue.
- **Context compaction**: when the conversation the model sees exceeds `context_char_budget` (default 400,000
  characters), old tool outputs are first replaced by "cleared, re-run if needed"; if that is not enough, the
  middle of the conversation is folded into a structured summary. The stored transcript is never rewritten, and
  the todo plan is re-attached afterwards.
- **Commands**: `sandbox.command_timeout` seconds per command (default 120), output capped at
  `sandbox.max_output_chars`.
- **Plan**: for multi-step work keep a `todo` plan and update it; if it has open items and was not updated for 8
  steps you get one reminder. The web UI shows the plan live.
- **Model calls**: only temporary errors (429, 5xx, timeouts, a dropped stream before any output) are retried —
  1, 2, 4 seconds, at most 3 times. Every call is recorded in a ledger (run, agent, purpose, input / cached /
  output tokens, duration; no message content), which feeds the Usage page.
- **Thinking**: thinking mode is on by default. Intensity is `off`, `default`, or a level (DeepSeek: low, medium,
  high, max; HKGAI: low, high, xhigh, max). A level the provider does not accept is sent as the nearest weaker one. Short internal calls
  (discussion turns, the approval guard, compaction) switch thinking off.
- **Stopping and resuming**: the human can stop a run at any time; an interrupted session is offered a Resume,
  which first completes tool calls that had no result and then continues from the record.
