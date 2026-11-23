# Suite builder and check validator

Scripts used to generate the YAML suites in `pland/eval/suites/` and to validate their checks.

- `build_<suite>.py` regenerates a suite's YAML files (data and expected values are computed, not typed by hand).
- `validate.py [suite ...]` builds each task's workspace exactly like the harness does, then runs the real
  checkers (`pland.eval.checks.run_check`) against (1) the unsolved setup — required checks must fail —,
  (2) a scripted reference solution (`ref_<suite>.py`) — every check must pass —, and (3) deliberately
  wrong variants (guessed units, edited tests, bypassed denials, hard-coded outputs, ...) — each must fail
  the checks it targets. No agent and no model API is involved.

```bash
.venv/bin/python tools/suite_builder/validate.py            # all suites
.venv/bin/python tools/suite_builder/validate.py midterm    # one suite
```

Web checks (PyPI, endoflife.date, example.com) need network access.
