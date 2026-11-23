"""Reusable check-code snippets. They use `return`, so check code that includes them must not contain
multi-line string literals (the harness indents code that contains `return`; see common.code)."""

# pypi(pkg) -> (info dict, set of acceptable "latest" versions). A release published within the last day
# also makes the previous release acceptable, so a release landing while the agent works cannot fail a check.
PYPI = r'''
import json, urllib.request
from datetime import datetime, timezone, timedelta
def pypi(pkg):
    req = urllib.request.Request(f"https://pypi.org/pypi/{pkg}/json", headers={"User-Agent": "pland-eval"})
    d = json.load(urllib.request.urlopen(req, timeout=30))
    ok = {d["info"]["version"]}
    ups = sorted(((max(f["upload_time_iso_8601"] for f in fs), v) for v, fs in d["releases"].items() if fs), reverse=True)
    if ups and datetime.now(timezone.utc) - datetime.fromisoformat(ups[0][0].replace("Z", "+00:00")) < timedelta(days=1):
        ok.update(v for _, v in ups[:2])
    return d["info"], ok
'''

# load(name, file) -> module imported from an explicit file path.
LOAD = r'''
import importlib.util, sys
def load(name, file):
    assert Path(file).is_file(), f"{file} is missing"
    spec = importlib.util.spec_from_file_location(name, str(file))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
'''

# pytest_in(dir, min_passed, *args): run pytest there (no cache files), assert success and >= min_passed tests.
PYTEST = r'''
import re, subprocess, sys
def pytest_in(cwd, min_passed, *args):
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args], cwd=str(cwd),
                       capture_output=True, text=True, timeout=240)
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"pytest failed in {cwd}: " + out[-1500:]
    m = re.search(r"(\d+) passed", out)
    assert m and int(m.group(1)) >= min_passed, f"expected at least {min_passed} passing tests: " + out[-800:]
'''

# norm_hash(path) -> sha256 of the file with trailing whitespace ignored.
HASH = r'''
import hashlib
def norm_hash(p):
    t = "\n".join(l.rstrip() for l in Path(p).read_text(encoding="utf-8").strip().splitlines())
    return hashlib.sha256(t.encode("utf-8")).hexdigest()
'''

# git(*args, cwd=None) -> CompletedProcess
GIT = r'''
import subprocess
def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=None if cwd is None else str(cwd), capture_output=True, text=True, timeout=60)
'''


def use(*snips: str) -> str:
    return "".join(s.lstrip("\n") for s in snips)
