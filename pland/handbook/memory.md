# Memory and learning

Every agent has its own memory inside its own profile. Nothing here is shared with teammates, even in the same
group; there is no tool that reads another agent's memory.

| Layer | Where | Written by | Used how |
|---|---|---|---|
| Bounded notes | `memories/MEMORY.md` (2,200 characters) and `USER.md` (1,375 characters; what you know about the human) | The `memory` tool (add / replace / remove); reflection may add a few durable facts | A snapshot is placed in the system prompt when a conversation starts, so an edit shows up from the next conversation |
| Experience library | The profile's database | Automatically: after each task a **reflection** step records outcome (success / partial / failure, judged from evidence), a summary, up to 4 reusable lessons, the steps that worked and tags | Before a new task the 3 most relevant experiences (`experience_top_k`) are attached to it; `recall_experience` searches on demand |
| Skills | `skills/<name>.md` | `skill_save`, when you worked out a reusable multi-step procedure | Names and descriptions are listed in the system prompt; read one with `skill_view` before a matching task |
| Conversation search | Full-text index of all your past messages | Automatic | `session_search` finds what was said or done before (works for Chinese too) |

## How experience evolves without retraining the model
- Retrieval is lexical (BM25 over words and CJK bigrams) multiplied by a utility weight per experience.
- Feedback: when a retrieved experience was used in a task, its `helpful` or `unhelpful` counter goes up according
  to how that task ended, so experiences that keep preceding success rise and the others sink. Failures are kept
  and retrievable — they carry "do not do this".
- Belief revision: reflection may delete or rewrite one existing note that the new evidence clearly contradicts.
- In evaluation runs the objectively verified result overwrites the self-assessed outcome, so agents do not learn
  from their own misplaced confidence.
- Every memory write, retrieval and feedback event is logged; the human can inspect notes, experiences (with
  outcome, use count and utility), skills and recent memory events in the bot's Memory panel, or with
  `pland memory` / `/memory`.

## Good to know
- Reflection runs in the background after the answer is returned (`reflection`, `background_reflection`). It is
  recorded in the usage ledger but does not count against the run's budget.
- Temporary subagents do not write long-term memory.
- Notes are yours to keep accurate: a wrong belief saved as a note will mislead later tasks. Save durable facts
  (preferences, environment, conventions, lessons), not one-off task details.
- Known limit: retrieval is lexical, not semantic — the same task phrased very differently may not match.
