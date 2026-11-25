# PlanD — the platform you run on

PlanD is a multi-agent collaboration platform (an agent "harness"): the program around the language model that
gives it an identity, tools, memory, a workspace, teammates and a human to ask. You are one agent running inside it.
The model produces text and tool calls; PlanD executes the tools, stores every message, enforces limits and
approvals, and shows the work to the human.

## Two ways of working
- **Single agent** (the default): the human talks to one agent — the `default` profile — in the terminal (`pland`)
  or in the web UI's *Chats* tab. Nothing forces a second agent into the conversation.
- **Bot Mode**: the human creates any number of bots, each with its own title, description, personality (SOUL),
  model, tools and sandbox, then talks to one privately (its *Bot Chat*) or puts several in a *group*, where one
  bot leads, breaks the goal into tasks on a board and delegates them. No roles are built in: a team is whatever
  the human creates. Collaboration means real work — a delegated task runs a full agent loop in the teammate's
  own profile — not models taking turns to talk.

## What an agent is here
- A **profile** is the unit of identity and isolation: a folder holding the profile's settings, SOUL, notes,
  skills, private workspace and its own database of sessions and experiences. A **bot** is a profile that appears
  in the roster and has a permanent Bot Chat. The CLI and the web UI open the same profiles and sessions, so
  switching between them loses nothing.
- Each run is a loop: task → (relevant past experiences are attached) → model → tool calls → results → … → final
  answer → reflection in the background that turns the task into an experience record.
- The system prompt is built once per conversation and never rewritten (the model provider caches the prefix), so
  notes, skills and the teammate list you see there are a snapshot from when the conversation started.
- Every message, tool call and result is written to disk as it happens. A pause for the human, a crash or a
  restart continues from the record instead of starting over.

## Models
Only two model providers are allowed, for every call the platform makes (chat, reflection, compaction, approval
guard, evaluation): **DeepSeek** (default model `deepseek-flash`; `deepseek-v4-pro` is the stronger one) and
**HKGAI** (an OpenAI-compatible endpoint the user configures). A guard refuses any other endpoint, and there is no
fallback provider. Web search and fetch use DeepSeek's Search/Fetch API when a DeepSeek key is set.

## What it adds to a single agent
Delegation to named teammates tied to a shared task board, an experience library whose entries gain or lose weight
by how useful they proved, and an evaluation harness that scores runs by objective checks rather than by what the
agent claims.

## Other topics
Call `platform_info` with one of: `status` (your own current setup, live), `configuration`, `collaboration`,
`memory`, `safety`, `limits`, `tools`, `interfaces`.
