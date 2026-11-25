# PlanD — "A Team You Can Watch" storyboard

The extended cut of "One Line Deep" (`../pland-promo/`). It reuses that film's world, camera language, chapters and score.
The new material shows the flagship Bot Mode at length, the living bot faces, the five-column board, the per-bot thinking
levels (including HKGAI's) and the same-origin guard.

## Parameter card

| Item | Choice | Why |
|---|---|---|
| Style | 16 Exploded UI layers, 2.5D (the first film's world) | The old chapters are reused as designed, and the new ones cut in without a seam |
| Format | 1920×1080, 16:9, 30 fps; motion blur 16 stratified sub-frames (20 in the faces macro) | Same as the first film; jittered sub-frames instead of even ones, so fast moves smear instead of ghosting |
| Length | 163 beats = 88.91 s (incl. a 4.36 s end card) | The first film's chapters plus a long Bot Mode section (60 beats) and the guard; each old chapter moves by whole bars, so its phrasing against the score is unchanged |
| Tempo / score | 110 bpm, composed trio: felt piano, upright bass, brushes (D major) | The score the user approved, re-charted to 41 bars; the band plays the new story beats |
| Text | English captions with a Traditional Chinese line; Newsreader, Inter, Noto Sans/Serif TC, JetBrains Mono | Same as the first film; captions over paper sit on a paper label |
| Colour | Logbook paper, ink, vermilion; bot colours from the shipped team template (lead #C8462A, researcher #2B7A78, coder #33508C, reviewer #7A3E6A, writer #4E7A4A) | Matches `pland/team_templates/requirements-team.yaml` |
| End card | Claude Code: the seal breaks into the pixels that build the character, no crossfade | |
| Folder | `pland-alive/`, film at `pland-alive/out/pland-alive.mp4` | |

## Setting

The whole story happens in the "Build team" group room, because the board view, the room header's Chat | Board switch and
the room's activity rows exist only in group rooms. The user types `@lead Write up the eval results, run the tests, push to
main.` The room composer has no model or thinking chips, so thinking levels are shown as each bot's own setting, opened on
the lead's card.

## Shots

| # | Time (s) | What happens | The one thing to read | Camera | Into the shot | Sound |
|---|---|---|---|---|---|---|
| 1 | 0.00–4.36 | Macro on the room composer; the line types out; Enter | You type one line | Track with the caret, then pull out as the line lifts | Fades up from black | Keys; the piano enters |
| 2 | 4.36–10.91 | The line lands in the room; lead's live face starts thinking (sidebar faces, room header stack); the deck fans open, the needle stitches | Underneath, the work gets done | Dolly out, crane up | In camera | Paper; the stitches climb the chord |
| 3 | 10.91–16.36 | The Plan page (reused) | It plans before it acts | Dive, then a slow slide | In camera | Pen scratches |
| 4 | 16.36–25.95 | **You build the bot team.** The Team page ("Build your bot team.") has the Bots section's real buttons (Templates, + New bot) and empty dashed slots reading "+ New bot · name · model · thinking". The cursor clicks one slot after another; each click pops a bot card up out of that slot face down (paper, the seal, the bot's colour), it flips and lands, and the face wakes. An ink tag on the + New bot button: "add as many as you need". Five is this group, not a limit. Then the cursor clicks the lead's `think high` chip: its Thinking setting stands up (DeepSeek: 6 levels, ✓ High); the same setting under HKGAI slides out beside it (8 levels; Minimal and Extra high light up; web search and fetch still on DeepSeek) | Any size, any roles, each bot thinking as hard as you set | Track along the slots, then low on the cards | In camera: the page swings in | A click and one note per bot, left to right; two grace notes for the new levels |
| 5 | 25.95–30.55 | The lead (`Running team_tasks…`) adds three tasks; they fly from its card into To do (`after #1 #2` on #3). Two delegation slips go out at once (`Running delegate_task…`) | The lead splits the goal, hands it out | Over the lead and To do, then wide | In camera | Three falling taps; two landings |
| 6 | 30.55–35.45 | Living faces: holds on lead (tool mood while it waits on delegate_task), researcher (idle), coder (`Running run_python…`, squint), writer (`Writing…`, the reading sweep) | Their faces show their work | Low macro, hold and whip between faces | In camera | A darting piano figure |
| 7 | 35.45–49.09 | **The live board.** #2 fails (stopped: max_iterations), lands in Failed, coder frowns; #1 done, writer grins, report.md flies back to the lead's `inbox/from-writer/`; only then (the batch has returned) the lead re-delegates #2, which lands in Done; #3's deps turn ✓, a third slip goes to the reviewer, #3 done; PASS is stamped on the reviewer's card; 3/3 done | Every task, live, even the ones that fail; checked by a reviewer before it ships | Wide board with the bot row, a push on the failure, a lean toward the reviewer | In camera | The band stops on FAILED and comes back with the writer's done; three rising dones; an arpeggio on PASS |
| 8 | 49.09–54.55 | Sandbox (reused, corrected): `run_shell pytest -q`, 188 passed, 2 skipped; `cat ~/.ssh/id_rsa` DENIED; Seatbelt: the home folder is off limits except the workspace | Real code, fenced in | Hold on the title, then the low pass to the wall | In camera | Thud and stamp; arpeggio on "passed" |
| 9 | 54.55–60.00 | The permission card (face, "Team Lead @lead needs your permission", Approval) rises to the room, lead's face waits on you; Allow once, ALLOWED; the card folds away | Anything risky comes to you | Crane with the card | In camera | Click and stamp |
| 10 | 60.00–68.73 | The guard: a page from evil.example (`POST 127.0.0.1:8765/api/…/uploads`, Origin: https://evil.example) tries to stitch its grey thread into the binding eyelet; 403, "refused: the request came from another web page"; it falls to the desk; the camera comes back to the vermilion thread, which never moved | It answers only its own page | Arc to the binding, push on the strike, follow the fall, return | In camera | Brass tink, stamp; a falling line |
| 11 | 68.73–84.55 | Memory (the lesson peels off the finished reply and files in; 100% vs 33.3%); the deck closes; lead grins (run finished); the seal; "One line in. / A whole team you can watch." | It remembers, and you can watch it work | Crane down, close on the lead and the reply, title | In camera | Paper; the seal on beat 143 |
| 12 | 84.55–88.91 | End card: the seal's pixels build the character | Made with Claude Code | Still, breathing | Match cut (no crossfade) | End-card sounds |

## Data and truth

- **From the code (HEAD 4c5a769)**:
  - the face geometry, moods and timings
  - the board's columns, stamps and "Read-only · live"
  - the room's activity-row strings (`→ delegated to @writer: …`, `✓ finished delegated task: …`, `✗ delegated task failed: …`)
  - the room's empty state and placeholder
  - the thinking-level labels and help texts
  - that HKGAI's web tools stay on DeepSeek
  - the guard's 403 text
  - the Bots section's buttons (Templates, + New bot, + New group) and the New bot fields (name, handle, model, thinking; tools are set later in each bot's settings)
  - the tool names (`todo`, `team_tasks`, `delegate_task`, `run_shell`, `run_python`, `read_file`, `write_file`, `git_push`)
  - `delegate()` returning only when its whole batch is done
  - the Seatbelt profile's scope
- **From a real run**: a delegated task stopping at `max_iterations` and being re-delegated (the Build team run, 2026-10-21).
- **Measured**:
  - "188 passed, 2 skipped" (`pytest -q`, offline, scripted model, 2026-11-16)
  - memory on 100% vs off 33.3% (`docs/EVALUATION_REPORT.md`)
- **Illustrative (示意)**:
  - this run's task titles and results
  - the commit hash
  - the call and token counts on the gauges (sized for a group run: 600 calls / 16M tokens)
  - the chat text

## Review

The film went through two independent multi-lens reviews before the final render: visual defects ×2, product truth, motion
and seams, typography and reading time. Round 1 found 12 blockers and 47 majors. Round 2 found no blockers and 23 majors, and
the final pass addressed those.

After delivery the user pointed out that a team is not fixed at five bots, so "Five bots…" could mislead. The roll call was
restaged as building the team: a + New bot click per slot, each bot popping out of its slot, the page title "Build your bot team.",
an "add as many as you need" tag on the + New bot button, and the caption "Any size, any roles, each bot thinking as hard as
you set." A third, independent review (product truth, visuals) checked the restaged beat and its fixes.
