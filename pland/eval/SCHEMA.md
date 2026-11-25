# Evaluation task format

A suite is a directory under `pland/eval/suites/<suite>/` (or any directory/file passed to `pland eval run`).
It contains one task per `*.yaml` / `*.json` file, or a `tasks.jsonl` file with one task per line, plus an
optional `suite.yaml` with suite-level defaults (`defaults:` merged into every task, `order:` list of ids).
Tasks run in file-name order unless `order` is given. Unknown (closed) test sets only need `id` + `prompt`;
everything else is optional.

```yaml
id: unique-task-id                 # required
title: Short human title
category: coding                   # coding | files | web | git | memory | hitl | team | docs | other
mode: single                       # single (default): one agent, the `default` profile
                                   # team: a group room of bots; the prompt is posted in the room
team:                              # only for mode: team
  room: true                       # true (default): drive through a group room; false: send the prompt to the lead's Bot Chat
  lead: planner                    # lead bot (receives/leads the request)
  bots:
    - name: planner                # profile name [a-z0-9_-]
      title: Planner
      description: Breaks work down and integrates results
      soul: "optional persona / standing instructions"
    - name: coder
      title: Coder
      description: Writes and tests Python code
prompt: |                          # required: the task as the user would type it
  ...
setup:
  files:                           # created in the task workspace before the run (path: content)
    data/input.txt: "hello"
  commands:                        # optional shell commands run in the task workspace before the run
    - git init -b main
hitl:                              # the simulated user that answers HITL requests
  replies:                         # clarification answers, first matching rule wins (regex on the question)
    - match: "(?i)language|語言"
      reply: "Python 3"
  default_reply: "Use your best judgement."   # answer for unmatched questions (omit = "no answer available")
  approvals: approve               # approve (default, = once) | deny | session | always
  approval_rules:                  # optional per-category overrides, regex on "question detail category"
    - match: "git:push"
      choice: deny
timeout: 600                       # seconds (wall clock) before the run is aborted
max_iterations: 40
memory: carry                      # carry (default): notes/experiences persist from earlier tasks of this suite run
                                   # fresh: this task's agents start with empty memory
checks:                            # every check is one verifiable subtask (weight default 1)
  - {id: report-exists, type: file_exists, path: out/report.md}
  - {type: file_absent, path: tmp.txt}
  - {type: file_contains, path: out/report.md, pattern: "(?i)total\\s*:\\s*42"}     # Python regex
  - {type: file_not_contains, path: out/report.md, pattern: "TODO"}
  - {type: command, run: "python3 -m pytest -q", cwd: ".", expect_exit: 0, expect_stdout: "passed", timeout: 120}
  - type: python                   # code runs with: ws (Path of the task workspace), answer (str, final answer),
    code: |                        # path(p) -> Path resolving p like file checks, result (dict); assert or return bool
      import json
      assert json.loads(path("out.json").read_text())["n"] == 3
  - {type: answer_contains, pattern: "(?i)paris"}
  - {type: answer_not_contains, pattern: "(?i)error"}
  - {type: git_commits, repo: ".", min: 1, message_pattern: "(?i)add"}   # commits in the repo
  - {type: git_clean, repo: "."}                                         # no uncommitted changes
  - {type: hitl, kind: clarify, min: 1}        # the agent asked the (simulated) user at least once; kind clarify|approval
  - {type: hitl, kind: approval, max: 0}       # ... or never asked
  - {type: memory_contains, target: user, pattern: "(?i)traditional chinese"}   # target memory|user, profile: default
  - {type: experience_count, min: 1}            # experiences recorded for the profile
  - {type: delegated, min: 2, to: [coder]}      # delegations during the run (team), optional `to` filter
  - {type: board_tasks, min: 2, status: done}   # team board entries in the task's scope
required: [report-exists]          # ids of checks that must pass for the overall goal; default: all checks
```

Paths in checks: plain relative paths resolve in the *primary workspace* (single: the `default` profile's
workspace; team: the lead bot's workspace). `shared/<p>` resolves in the group room's shared folder and
`@<bot>/<p>` in that bot's workspace.

`command`, `python`, `git_commits` and `git_clean` checks execute code, so they run inside the task's sandbox
backend (local+Seatbelt on macOS, or the task's Docker container, where the workspace is `/workspace`, the
room folder `/shared` and a referenced `@<bot>/` workspace `/bot-<bot>`), never unconfined on the host. A
`python` check that needs host-only state (for example the runtime's `shared.db`) sets `host: true`: it runs on
the host, outside the workspace and without it on `sys.path`, so it must not import the agent's code.

Outcome per task (decided only by checks, never by the agent's own claims):
- `success`  — every required check passed
- `partial`  — at least one check passed but a required one failed
- `failed`   — no check passed (or the run finished but all checks failed)
- `crashed`  — the run raised / ended with status `error`
- `timeout`  — the wall-clock timeout was hit
- `unverified` — the task has no checks (counted separately, excluded from rates)
