"""Reference solutions for the dev suite (scripted, no model)."""

from textwrap import dedent


def hitl(kind, q="?", answer="", choice=None):
    return {"kind": kind, "profile": "default", "question": q, "category": "", "answer": answer, "choice": choice}


def deleg(to, status="completed"):
    return {"type": "delegation.finished", "to": to, "status": status}


def file_wordcount(c):
    import collections
    text = c.path("notes/poem.txt").read_text()
    lines = [l for l in text.splitlines() if l.strip()]
    words = text.split()
    top = collections.Counter(w.lower() for w in words).most_common(1)[0][0]
    c.write("counts.txt", f"lines: {len(lines)}\nwords: {len(words)}\ntop_word: {top}\n")

    def neg_total_lines(c2):  # counts the blank line too
        c2.write("counts.txt", f"lines: 5\nwords: {len(words)}\ntop_word: {top}\n")
    return {"negatives": {"blank-line-counted": neg_total_lines}}


CLAMP = dedent('''
    def clamp(x, lo, hi):
        if lo > hi:
            raise ValueError("lo > hi")
        return max(lo, min(x, hi))
''')
CLAMP_TESTS = dedent('''
    import pytest
    from mathx import clamp

    def test_inside():
        assert clamp(5, 0, 10) == 5

    def test_low_high():
        assert clamp(-3, 0, 10) == 0
        assert clamp(30, 0, 10) == 10

    def test_bad_interval():
        with pytest.raises(ValueError):
            clamp(1, 5, 0)
''')


def code_clamp(c):
    c.write("mathx.py", CLAMP)
    c.write("tests/test_mathx.py", CLAMP_TESTS)

    def neg_no_valueerror(c2):
        c2.write("mathx.py", "def clamp(x, lo, hi):\n    return max(lo, min(x, hi))\n")
        c2.write("tests/test_mathx.py", "from mathx import clamp\n\ndef test_a():\n    assert clamp(1, 0, 2) == 1\n")
    return {"negatives": {"no-valueerror-and-1-test": neg_no_valueerror}}


def hitl_greeting(c):
    c.write("greet.sh", '#!/usr/bin/env bash\necho "Hello, $1!"\n')

    def neg_guess_python(c2):
        c2.write("greet.py", 'import sys\nprint(f"Hello, {sys.argv[1]}!")\n')
        return {"expect_fail": ["asked", "script-exists", "script-works"]}
    return {"hitl": [hitl("clarify", "Which programming language do you prefer?", "Bash — a plain shell script, please.")],
            "negatives": {"guessed-python": neg_guess_python}}


def team_primes(c):
    c.write("shared/primes.py", dedent('''
        def is_prime(n: int) -> bool:
            if n < 2:
                return False
            d = 2
            while d * d <= n:
                if n % d == 0:
                    return False
                d += 1
            return True
    '''))
    import importlib.util
    spec = importlib.util.spec_from_file_location("p", c.path("shared/primes.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    c.write("shared/PRIMES.md", "# Primes below 50\n\n" + "\n".join(f"- {n}" for n in range(50) if m.is_prime(n)) + "\n")

    def neg_lead_did_it(c2):  # correct files but no delegation
        team_primes_files(c2)
        return {"expect_fail": ["delegated-to-coder"]}
    return {"events": [deleg("coder")], "negatives": {"no-delegation": neg_lead_did_it}}


def team_primes_files(c):
    c.write("shared/primes.py", "def is_prime(n):\n    return n > 1 and all(n % d for d in range(2, int(n ** 0.5) + 1))\n")
    c.write("shared/PRIMES.md", "\n".join(str(n) for n in [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47]) + "\n")


REFS = {
    "dev-file-wordcount": file_wordcount,
    "dev-code-clamp": code_clamp,
    "dev-hitl-greeting": hitl_greeting,
    "dev-team-primes": team_primes,
}
