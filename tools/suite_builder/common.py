"""Shared helpers for building the PlanD evaluation suites as YAML files."""

from __future__ import annotations

import hashlib
import re
import textwrap
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SUITES = REPO / "pland" / "eval" / "suites"

KEY_ORDER = ["id", "title", "category", "mode", "team", "prompt", "setup", "hitl", "timeout", "max_iterations",
             "memory", "checks", "required"]


class Dumper(yaml.SafeDumper):
    pass


def _str(d, s):
    if "\n" in s:
        return d.represent_scalar("tag:yaml.org,2002:str", s, style="|")
    return d.represent_scalar("tag:yaml.org,2002:str", s)


Dumper.add_representer(str, _str)


def _is_scalar(v) -> bool:
    return isinstance(v, (int, float, bool)) or (isinstance(v, str) and "\n" not in v)


def _dict(d, data):
    flat = all(_is_scalar(v) or (isinstance(v, list) and len(v) <= 4 and all(_is_scalar(x) for x in v))
               for v in data.values())
    if flat and data and "type" in data and len(repr(data)) <= 105:
        return d.represent_mapping("tag:yaml.org,2002:map", data.items(), flow_style=True)
    return d.represent_mapping("tag:yaml.org,2002:map", data.items(), flow_style=False)


def _list(d, data):
    flow = data and len(data) <= 4 and all(_is_scalar(x) for x in data) and len(repr(data)) <= 80
    return d.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=bool(flow))


Dumper.add_representer(dict, _dict)
Dumper.add_representer(list, _list)


def lit(s: str) -> str:
    """Dedent a triple-quoted block and make it end with exactly one newline."""
    s = textwrap.dedent(s)
    if s.startswith("\n"):
        s = s[1:]
    return s.rstrip("\n") + "\n"


def code(s: str, **subs) -> str:
    """Check code. `__NAME__` placeholders are replaced by repr(subs['NAME'])."""
    s = lit(s)
    for k, v in subs.items():
        token = f"__{k}__"
        assert token in s, f"placeholder {token} not used"
        s = s.replace(token, repr(v))
    # The harness wraps code containing `return` into a function (indenting every line), which would alter
    # multi-line string literals -- so never combine the two.
    if re.search(r"^\s*return\b", s, re.M):
        assert '"""' not in s and "'''" not in s, "check code with `return` must not contain multi-line strings"
    return s


def norm_hash(text: str) -> str:
    """Hash that ignores trailing whitespace / final newline differences."""
    norm = "\n".join(line.rstrip() for line in text.strip().splitlines())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def ordered(task: dict) -> dict:
    out = {k: task[k] for k in KEY_ORDER if k in task}
    out.update({k: v for k, v in task.items() if k not in out})
    return out


def dump(data: dict) -> str:
    text = yaml.dump(data, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=10000, default_flow_style=False)
    return text


def write_task(suite: str, fname: str, task: dict, header: str = "") -> Path:
    d = SUITES / suite
    d.mkdir(parents=True, exist_ok=True)
    text = dump(ordered(task))
    # Every multi-line string must have been emitted as a literal block (readability + exactness).
    for key in ("prompt",):
        assert f"{key}: |" in text, f"{fname}: {key} not emitted as literal block"
    if header:
        text = "".join(f"# {line}\n" if line else "#\n" for line in header.strip().splitlines()) + text
    p = d / fname
    p.write_text(text, encoding="utf-8")
    # round-trip sanity
    back = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert back == ordered(task), f"{fname}: YAML round-trip mismatch"
    return p


def write_suite(suite: str, meta: dict, header: str = "") -> Path:
    d = SUITES / suite
    d.mkdir(parents=True, exist_ok=True)
    text = dump(meta)
    if header:
        text = "".join(f"# {line}\n" if line else "#\n" for line in header.strip().splitlines()) + text
    p = d / "suite.yaml"
    p.write_text(text, encoding="utf-8")
    assert yaml.safe_load(p.read_text(encoding="utf-8")) == meta
    return p
