# Interfaces: terminal, web, evaluation

## Terminal (`pland`)
- `pland` or `pland chat` — talk to one agent. Options: `-p <profile>` (a bot), `--bot-chat` (that bot's
  permanent Bot Chat, the same conversation the web UI shows), `-w <folder>` (working folder; by default a new
  chat works in the folder it was started from), `-q "<question>"` (one question, print the answer and exit),
  `-c` (continue the most recent chat), `--session <id>`, `--reasoning <level>`, `--yolo` (skip approval prompts
  for this run; hard blocks still apply).
- Inside a chat: `/new`, `/sessions`, `/resume <id>`, `/workspace [folder]`, `/model [id]`, `/reasoning [level]`,
  `/memory`, `/experience`, `/help`, `/exit`.
- `pland setup` — API key, model, thinking intensity, sandbox and approvals for the default profile.
- `pland profile …` — create, list, show, change or delete profiles (bots).
- `pland team` — list or apply team templates (ready-made example bots and groups; roles are just data).
- `pland memory` — show a profile's notes and experiences.
- `pland doctor` — check the configuration; `--probe` makes a few small real model calls.
- `pland serve` — start the web server (127.0.0.1:8765 by default). `pland desktop` — open the web UI in its own
  app window, starting the server in the background if needed (`--stop` stops it).
- `pland eval` — the evaluation harness (below).
Bot Mode lives in the web UI; the terminal covers profiles and conversations, not rosters, groups or boards.

## Web UI
- **Sidebar**: *Chats* (conversations with the default agent) and *Bots & groups* (roster with live status and
  "waiting for you" markers; `+ New bot`, `+ New group`, `Templates`).
- **Conversation**: Markdown answers, tool-call cards (arguments, result, duration), the live plan, a status line,
  streaming text. The composer has `+` to upload files (also drag-and-drop or paste; saved under `uploads/`; PDF
  and Office documents are refused), the model and thinking-intensity menus for this conversation, and Stop while
  a run is going.
- **Groups**: speaker names, the lead's star, activity lines for delegations, `@` autocomplete, a Chat / Board
  switch for the full-width task board.
- **Right-hand panel**: for a bot — Memory (notes, experiences, skills, recent memory events), board, sessions,
  files, settings; for a group — board, members, files, settings.
- **Requests for the human**: clarification cards (option buttons and free text) and approval cards (Allow once /
  Session / Always / Deny), collected in a global tray.
- **Settings**: Appearance, Model (provider and keys), Agent, Sandbox & folders, Run limits, Usage (calls, tokens,
  cache hits, cost per day and per bot), Keyboard, About.
- Bots have a small animated face as avatar: it looks around while the bot is working and shows whether it is
  thinking, running a tool, writing or waiting for the human.

## Evaluation harness
`pland eval run <suite>` runs a task suite against the real model and scores it by objective checks only (files,
content, commands and tests, git history, human-interaction counts, memory, delegations, board tasks) — never by
an agent's own claim. Each suite run uses a separate data folder with clean workspaces. It reports goal
completion, sub-task completion, outcome distribution, wall-clock time, model calls, tokens, cache hits and
estimated cost, and keeps the event stream, transcript and workspace snapshot of every task. Options include
`--memory off`, `--passes N`, `--backend docker`, `--reasoning <level>`; `pland eval list`, `report`, `compare`.

## Where things are stored
`PLAND_HOME` (default `~/.pland`): `profiles/<name>/` (profile.yaml, SOUL.md, memories/, skills/, workspace/,
state.db), `shared.db` (group transcripts, task board, deliveries, requests for the human, the model-call ledger),
`settings.yaml` (global defaults), `logs/`, `eval_runs/`.
