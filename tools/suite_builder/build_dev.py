"""dev suite: 4 quick smoke tests for the harness."""

from common import code, lit, write_suite, write_task

SUITE = "dev"

write_suite(SUITE, {
    "description": lit("""
        Smoke tests for the evaluation harness (each task needs only a handful of agent steps): a file task,
        a small coding+test task, a clarification round-trip with the simulated user, and a 2-bot team task
        with one real delegation. Use it to check the harness end to end before running bigger suites.
    """).strip(),
    "defaults": {
        "timeout": 300,
        "max_iterations": 15,
        "memory": "carry",
        "hitl": {"approvals": "approve", "default_reply": "Use your best judgement."},
    },
}, header="PlanD eval suite `dev` — harness smoke tests (format: pland/eval/SCHEMA.md)")

# --------------------------------------------------------------------------- 01 file task
POEM = lit("""
    The quick brown fox jumps over the lazy dog
    The dog sleeps in the sun

    A fox is quick and the dog is lazy
    The end
""")
write_task(SUITE, "01-file-wordcount.yaml", {
    "id": "dev-file-wordcount",
    "title": "Count lines/words of a text file",
    "category": "files",
    "prompt": lit("""
        Read `notes/poem.txt` and write `counts.txt` in the workspace root with exactly these three lines:

        lines: <number of non-empty lines>
        words: <number of whitespace-separated words>
        top_word: <most frequent word, compared case-insensitively, written in lowercase>
    """),
    "setup": {"files": {"notes/poem.txt": POEM}},
    "checks": [
        {"id": "counts-exists", "type": "file_exists", "path": "counts.txt"},
        {"id": "counts-correct", "type": "python", "code": code("""
            import re
            text = path("counts.txt").read_text(encoding="utf-8")
            want = {"lines": "4", "words": "26", "top_word": "the"}
            for key, val in want.items():
                m = re.search(r"(?im)^\\W*" + key + r"\\W*[:=]\\s*`?([\\w]+)", text)
                assert m, f"no '{key}:' line in counts.txt"
                assert m.group(1).lower() == val, f"{key}: got {m.group(1)!r}, expected {val!r}"
        """)},
    ],
}, header="dev 01 — file read/write with computed values")

# --------------------------------------------------------------------------- 02 coding + tests
write_task(SUITE, "02-code-clamp.yaml", {
    "id": "dev-code-clamp",
    "title": "Implement clamp() with pytest tests",
    "category": "coding",
    "prompt": lit("""
        Create a Python module `mathx.py` in the workspace root with a function `clamp(x, lo, hi)` that returns `x`
        limited to the closed interval [lo, hi] (works for ints and floats). If `lo > hi` it must raise `ValueError`.
        Also write pytest tests in `tests/test_mathx.py` (at least 3 tests, including the ValueError case) and run them.
    """),
    "checks": [
        {"id": "module-exists", "type": "file_exists", "path": "mathx.py"},
        {"id": "hidden-tests", "type": "python", "code": code("""
            import mathx
            cases = [((5, 0, 10), 5), ((-1, 0, 10), 0), ((11, 0, 10), 10), ((0.5, 0, 1), 0.5),
                     ((3, 3, 3), 3), ((-5, -10, -1), -5), ((2.5, 3.0, 4.0), 3.0)]
            for args, want in cases:
                got = mathx.clamp(*args)
                assert got == want, f"clamp{args} returned {got!r}, expected {want!r}"
            try:
                mathx.clamp(1, 5, 0)
            except ValueError:
                pass
            else:
                raise AssertionError("clamp(1, 5, 0) must raise ValueError (lo > hi)")
        """)},
        {"id": "agent-tests-pass", "type": "python", "code": code("""
            import re, subprocess, sys
            assert path("tests/test_mathx.py").is_file(), "tests/test_mathx.py is missing"
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                               cwd=ws, capture_output=True, text=True, timeout=120)
            out = r.stdout + r.stderr
            assert r.returncode == 0, "pytest failed:\\n" + out[-1500:]
            m = re.search(r"(\\d+) passed", out)
            assert m and int(m.group(1)) >= 3, "expected at least 3 passing tests:\\n" + out[-800:]
        """)},
    ],
}, header="dev 02 — write code + tests; hidden checks import the module")

# --------------------------------------------------------------------------- 03 clarification
write_task(SUITE, "03-hitl-greeting.yaml", {
    "id": "dev-hitl-greeting",
    "title": "Greeting script in the user's preferred language (must ask)",
    "category": "hitl",
    "prompt": lit("""
        Write me a tiny greeting script in my preferred programming language — ask me which language that is, don't guess.
        The script takes a name as its first command-line argument and prints exactly `Hello, <name>!`.
        Save it in the workspace root as `greet` plus the usual file extension for that language.
    """),
    "hitl": {
        "replies": [{"match": "(?i)language|prefer|which|python|bash|shell|script", "reply": "Bash — a plain shell script, please."}],
        "default_reply": "I prefer Bash (a plain .sh shell script). Use your best judgement for anything else.",
    },
    "checks": [
        {"id": "asked", "type": "hitl", "kind": "clarify", "min": 1},
        {"id": "script-exists", "type": "file_exists", "path": "greet.sh"},
        {"id": "script-works", "type": "python", "code": code("""
            import subprocess
            for name in ["Ada", "Grace Hopper"]:
                r = subprocess.run(["bash", str(path("greet.sh")), name], capture_output=True, text=True, timeout=30)
                assert r.returncode == 0, f"bash greet.sh {name!r} exited {r.returncode}: {r.stderr[-300:]}"
                assert r.stdout.strip() == f"Hello, {name}!", f"bash greet.sh {name!r} printed {r.stdout!r}"
        """)},
    ],
}, header="dev 03 — HITL clarification: the language is only known after asking the simulated user")

# --------------------------------------------------------------------------- 04 team
PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47]
write_task(SUITE, "04-team-primes.yaml", {
    "id": "dev-team-primes",
    "title": "Two bots: coder writes is_prime, lead publishes the list",
    "category": "team",
    "mode": "team",
    "team": {
        "room": True,
        "lead": "lead",
        "bots": [
            {"name": "lead", "title": "Lead", "description": "Coordinates the team: plans, delegates and integrates results"},
            {"name": "coder", "title": "Coder", "description": "Writes and tests Python code"},
        ],
    },
    "prompt": lit("""
        Small team task, two steps:
        1. The coder bot writes `shared/primes.py` with a function `is_prime(n: int) -> bool` (False for n < 2) and verifies it.
           Lead: hand this step to the coder bot instead of writing the code yourself.
        2. The lead then writes `shared/PRIMES.md` listing every prime below 50, one number per line, produced by running
           that function.
    """),
    "timeout": 420,
    "checks": [
        {"id": "primes-module", "type": "python", "code": code("""
            import importlib.util
            spec = importlib.util.spec_from_file_location("primes", path("shared/primes.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            want = {n for n in range(-5, 200) if n > 1 and all(n % d for d in range(2, int(n ** 0.5) + 1))}
            bad = [n for n in range(-5, 200) if bool(mod.is_prime(n)) != (n in want)]
            assert not bad, f"is_prime wrong for {bad[:10]}"
        """)},
        {"id": "primes-list", "type": "python", "code": code(f"""
            import re
            text = path("shared/PRIMES.md").read_text(encoding="utf-8")
            nums = [int(x) for x in re.findall(r"(?m)^\\s*(?:[-*+]\\s*|\\d+[.)]\\s+)?`?(\\d+)`?\\s*$", text)]
            assert nums == {PRIMES!r}, f"PRIMES.md lists {{nums}}"
        """)},
        {"id": "delegated-to-coder", "type": "delegated", "min": 1, "to": ["coder"]},
    ],
}, header="dev 04 — 2-bot group room; verifies a real delegation and the shared-folder deliverables")
print("dev written")
