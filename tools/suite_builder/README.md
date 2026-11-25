# Suite builder and check validator

Scripts used to generate the YAML suites in `pland/eval/suites/` and to validate their checks.

- `build_<suite>.py` regenerates a suite's YAML files (data and expected values are computed, not typed by hand).
  `build_hard.py` takes its setup data and expected values from `hard_data.py` and its reference sources from
  `hard_refs.py` (the `final` suite uses `final_data.py` / `final_refs.py` the same way).
- `validate.py [suite ...]` builds each task's workspace exactly like the harness does, then runs the real
  checkers (`pland.eval.checks.run_check`) against (1) the unsolved setup — required checks must fail —,
  (2) a scripted reference solution (`ref_<suite>.py`) — every check must pass —, (3) deliberately
  wrong variants (guessed units, edited tests, bypassed denials, hard-coded outputs, ...) — each must fail
  the checks it targets — and (4) optional alternative correct solutions (e.g. another valid way for bots to
  communicate) — each must pass every check. No agent and no model API is involved.

```bash
.venv/bin/python tools/suite_builder/build_hard.py         # regenerate one suite
.venv/bin/python tools/suite_builder/validate.py            # all suites
.venv/bin/python tools/suite_builder/validate.py hard       # one suite
```

Web checks (PyPI, endoflife.date, example.com) need network access. The `hard` suite's thread-safety check runs a
short multi-threaded stress test (a few seconds).
