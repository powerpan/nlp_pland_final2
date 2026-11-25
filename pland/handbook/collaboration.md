# How agents work together

Agents share nothing by default: each has its own notes, experiences, skills, sessions and workspace, and being in
the same group does not change that. Information crosses between agents through four explicit channels only.

| Channel | What happens | Use it for |
|---|---|---|
| `delegate_task` | A new *delegation* session starts in the teammate's own profile and runs a full agent loop with the teammate's tools, memory and workspace; a structured report comes back | Real work: code, research, writing, review |
| `message_agent` | The message is delivered to the teammate's main Bot Chat, it runs one turn and the reply comes back (synchronous; `timeout`, default 900 s, bounds the wait and the teammate's turn; if the teammate is waiting on you, it fails at once with a "would deadlock" error) | A question, a quick check, an opinion |
| Group room | A conversation shared by the human and several bots; each bot sees the messages posted since its last turn | Discussion, negotiation, the lead driving a goal |
| Files | `share_file` copies a file into a teammate's `inbox/from-<you>/` or the group's `shared/` folder; a delegation can attach `files` | Handing over results |

## Delegation
- `delegate_task(tasks=[{to, goal, context, files, expected_output, task_id}, …])`. The delegate cannot see your
  conversation: it gets only the goal, context, attachments and (in a group) the `shared/` folder, so give full
  context. Several independent tasks in one call run in parallel (up to `max_parallel_delegations`, default 4).
- Without `to`, the task goes to a **temporary subagent** of yourself: same profile and workspace, fresh context,
  no questions to the human, no long-term memory writes, no team messages; only its summary returns.
- Files a delegate wrote (the ones named in `expected_output` plus what it wrote in that run, up to 12 files of
  20 MB each) are copied back into your folder under `inbox/from-<name>/` and listed in the result.
- Each delegation creates or links a task on the board and moves it `in_progress → done / failed`. A delegation
  linked to a board task is refused while that task's prerequisites are unfinished; once they are done, their
  results are attached to the delegate's brief.
- Pass the planned card's `task_id` on the first independent review and on revisions. Each independent criterion
  has its own report path. When the team has several plausible cards, the tool returns their IDs so the sender can
  choose the right one.
- For a requirement that depends on the deliverable in use, set `review.observation` to the specific result to
  verify. A passing report records `Evidence: observed | <method and result>` immediately below its verdict.
  Report a proxy as `estimated` or a missing observation as `unavailable`; either leaves the requirement open.
  Content and analytical reviews can establish their criteria by inspecting the work itself. When the requested
  output is an estimate, review its method and result as an estimate.
- Loop protection: every run carries its delegation chain; a target already in the chain (A → B → A) is refused,
  and the depth is capped (`max_delegation_depth`, default 2).
- A delegate's questions and approval requests go to the same human, under the delegate's name; permission is
  never bypassed by delegating.
- All delegates of one top-level run share that run's budget (see the `limits` topic).

## The task board (`team_tasks`)
The explicit record of how a goal was split and who owns what: title, description, assignee, status
(`todo / in_progress / done / failed / blocked`), dependencies, result. Its scope is the group, or outside a group
the delegating agent. The web UI shows it live (right-hand panel, and a full-width Board view per group). The
board is read-only for the human: the lead creates tasks and delegations move them.

## Groups: who speaks when
1. The human posts. Recipients are the bots mentioned with `@name` — or everyone with `@all` or no mention.
2. The **lead** for this request is the group's configured lead if it is among the recipients, else the first bot
   mentioned, else the first member. Any bot can lead; it is chosen per request, not a fixed role.
3. Round 1: the other recipients take a short **discussion turn** in parallel — read-only, at most 6 steps, to say
   what part suits them, what risks they see and what they know, or `[PASS]` if they have nothing to add. Then
   the lead acts with their input: splits the goal on the board, delegates, integrates and verifies.
4. Later rounds: only members a bot mentioned with `@name` get a turn (full tools, at most 40 steps). Mention a
   teammate only when you need it to act.
5. The drive ends when a round is silent, after 3 rounds or 12 messages, when the budget is nearly used, or when
   a bot writes `@user` — that raises a "needs you" flag for the human.
Each member keeps one persistent session per group (its private view of the room) across drives.

## Fast Mode (on by default for new groups)
Bounds how much checking a group does for one request. It changes no one's thinking: every bot keeps its own
configured reasoning level. While it is on:
- Only the checks required for acceptance run. Every shell or Python command stops after 25 s, and the whole team
  (lead, delegates, their subagents) has 90 s of command time per request; time is reserved before a command starts,
  so parallel work cannot exceed it. When it is used up, commands are refused.
- A board card can carry its acceptance scope: `team_tasks add/update` with `files` and `checks`. `run_checks(task_id)`
  runs the card's checks; a check that already passed on the same file contents (SHA-256) is not run again.
- Use `delegate_task` with `review={criterion, inputs, report}`. State the user requirement; start a different card
  for an independent requirement on the same artifact. Reuse needs matching versions, scope, context and a valid
  report. Keep the same criterion on the original card when continuing unfinished work or reviewing a revision.
- Initial and revision reviews have separate time settings (210 s initially, 120 s for a revision, up to 16 steps each). A card has one
  revision and one continuation. Record evidence early under `Verdict: INCOMPLETE` until a verdict is supported.
  When an independent check can start on a stable draft, run it alongside work on unrelated requirements.
- The closing summary lists verified deliverables. When checks are still open it also shows which files exist.
  Supporting inputs remain part of the review evidence. The summary explains what still needs checking — for
  example a check that was not run because the time ran out, or a file changed after its review.

## Workspaces in a team
A delegate works in its own private workspace. In a group, `shared/` (relative to each member's workspace) is the
common folder; the human can point it at a real project folder. Uploads from the human land in `uploads/`.

## Revisions and conflicting evidence

On a revision, pass the existing review card and put the requested focus in the goal. The card retains its
acceptance criterion and observation. Shared regular files attached to a review are versioned with the
declared inputs. The reviewer gets the changes, earlier evidence and open findings. Recheck behavior
affected by the edits. When a fresh observation is requested, check the current condition again and
use earlier evidence for unaffected checks. Unversioned private context can require a full review.
After a PASS, optional editorial suggestions can wait unless the user requested them.

When two viable interpretations still lead to different decisions, anyone on the team can record the alternatives with
`team_tasks(action="flag_conflict", title=..., description=..., source=...)`. Use an exact shared file
path or a source locator and put the passage/version in the description. On that card request an independent
review of the affected deliverables. The report records the deciding source, a distinguishing check and
its result. An expected draft correction belongs on its original card. An unresolved dispute carries
into follow-ups in the same room. For an independent new request, the lead can use `team_tasks(action="separate_request")`
on the old dispute with an explanation. The original card stays open. Questions answered by the source
belong on the original work card. The lead can handle a simple request directly.

The team defers learning from a group request until its checks settle. To save the outcome of a dispute,
use `memory(action="add", target="memory", verified_task_id=...)`. The same call can save an independent
observation from another passing card. In both cases the stored text comes from the signed report.
When the human states a preference, `memory(action="add", target="user", user_quote=...)` saves their
exact words immediately.
