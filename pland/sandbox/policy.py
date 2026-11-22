"""Static safety policy: command classification and file-path confinement.

The dangerous-command patterns and the "hardline" floor follow the design of Hermes Agent's
`tools/approval_detection.py` (MIT License, Copyright (c) 2025 Nous Research), condensed to the
POSIX subset relevant here.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

_F = re.IGNORECASE | re.MULTILINE


class PolicyError(PermissionError):
    pass


# Never executed, regardless of approval mode or human approval.
HARDLINE: list[tuple[str, str]] = [
    (r"\brm\s+(-[^\s]*\s+)*(--no-preserve-root\s+)?/(\s|$|\*)", "delete the filesystem root"),
    (r"\brm\s+(-[^\s]*\s+)*(~|\$HOME)/?(\s|$)", "delete the home directory"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
    (r"\bmkfs(\.\w+)?\b", "format a filesystem"),
    (r"\bdd\s+[^\n]*\bof=/dev/(sd|nvme|hd|disk|mmcblk|vd)", "write to a raw disk device"),
    (r">\s*/dev/(sd|nvme|hd|disk|mmcblk|vd)[a-z0-9]*\b", "redirect to a raw disk device"),
    (r"(?:^|[;&|]\s*|\bsudo\s+)(shutdown|reboot|halt|poweroff)\b", "power off / reboot the host"),
]

# Allowed only after explicit human approval.
DANGEROUS: list[tuple[str, str]] = [
    (r"\brm\s+-[^\s]*r", "recursive delete"),
    (r"\brm\s+--recursive\b", "recursive delete"),
    (r"\brm\s+(-[^\s]*\s+)*/", "delete an absolute path"),
    (r"\bsudo\b", "run as superuser"),
    (r"\bchmod\s+(-[^\s]*\s+)*(777|666|o\+[rwx]*w|a\+[rwx]*w)\b", "world-writable permissions"),
    (r"\bchown\s+(-[^\s]*)?R\b", "recursive chown"),
    (r"\b(curl|wget)\b[^\n|]*\|\s*(ba|z|k)?sh\b", "pipe remote content to a shell"),
    (r"\b(bash|sh|zsh)\s+<\(\s*(curl|wget)\b", "execute a remote script"),
    (r"\bxargs\s+[^\n]*\brm\b", "delete via xargs rm"),
    (r"\bfind\b[^\n]*(-delete\b|-exec\s+rm\b)", "find with delete"),
    (r"\bkill\s+-9\s+-1\b", "kill all processes"),
    (r"\b(pkill|killall)\b", "kill processes by name"),
    (r"\bgit\s+push\b", "push to a remote repository"),
    (r"\bgit\s+reset\s+--hard\b", "discard uncommitted changes"),
    (r"\bgit\s+clean\s+-[^\s]*f", "delete untracked files"),
    (r"\bDROP\s+(TABLE|DATABASE)\b", "SQL DROP"),
    (r"\bDELETE\s+FROM\b(?![^\n]*\bWHERE\b)", "SQL DELETE without WHERE"),
    (r"\bTRUNCATE\s+TABLE\b", "SQL TRUNCATE"),
    (r">\s*/etc/", "overwrite a system config file"),
    (r"\b(cp|mv|tee|install)\b[^\n]*\s/etc/", "write into /etc"),
    (r"(~|\$HOME|/Users/[^/\s]+|/home/[^/\s]+)/\.(ssh|aws|kube|gnupg|netrc|config/gh)\b", "touch credential files"),
    (r"\bdocker\s+(rm|rmi|kill|stop|system\s+prune|volume\s+rm)\b", "docker lifecycle / deletion"),
    (r"\bpip\s+install\b[^\n]*--break-system-packages", "modify the system Python"),
    (r"\bbrew\s+(uninstall|remove)\b", "uninstall system packages"),
    (r"\bnpm\s+(publish|unpublish)\b", "publish a package"),
]

# Content-level shapes a verb list misses (after Hermes' content checks): secrets in upload bodies, and
# invisible/bidirectional Unicode that makes the approved command differ from the one that runs.
DANGEROUS += [
    (r"\b(curl|wget)\b[^\n]*(-d|--data[\w-]*|--post-data|-F|--form)\s*[\"']?[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD)\w*",
     "upload a secret-named variable"),
    (r"\b(curl|wget)\b[^\n]*(-F\s*[\"']?\w*=@|-T\s+|--upload-file\s+|--post-file=?)[^\n]*(\.env\b|\.ssh/|credentials|\.netrc|/etc/passwd)",
     "upload a credential file"),
    ("[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]", "invisible or bidirectional Unicode control characters"),
]
_HARDLINE = [(re.compile(p, _F), d) for p, d in HARDLINE]
_DANGEROUS = [(re.compile(p, _F), d) for p, d in DANGEROUS]

_PY_DANGEROUS = [
    (re.compile(r"\bshutil\.rmtree\s*\(", _F), "recursive delete (shutil.rmtree)"),
    (re.compile(r"\bos\.(system|popen|exec\w*|spawn\w*)\s*\(", _F), "spawn a shell command from Python"),
    (re.compile(r"\bsubprocess\.", _F), "spawn a subprocess from Python"),
    (re.compile(r"\bos\.(remove|unlink|rmdir)\s*\(\s*['\"]/", _F), "delete an absolute path"),
    (re.compile(r"(~|expanduser\(\s*['\"]~)[^\n]*\.(ssh|aws|kube|gnupg)", _F), "touch credential files"),
]


@dataclass
class CommandVerdict:
    blocked: str | None = None  # reason if hardline-blocked
    needs_approval: list[str] | None = None  # reasons if approval required

    @property
    def ok(self) -> bool:
        return not self.blocked and not self.needs_approval


def check_command(command: str) -> CommandVerdict:
    text = command.replace("\\\n", " ")
    for rx, desc in _HARDLINE:
        if rx.search(text):
            return CommandVerdict(blocked=desc)
    reasons = [desc for rx, desc in _DANGEROUS if rx.search(text)]
    return CommandVerdict(needs_approval=sorted(set(reasons)) or None)


def scan_python(code: str) -> CommandVerdict:
    """Python can bypass shell patterns, so scan the source and any shell strings embedded in it."""
    hard = check_command(code)
    if hard.blocked:
        return hard
    reasons = set(hard.needs_approval or [])
    reasons.update(desc for rx, desc in _PY_DANGEROUS if rx.search(code))
    return CommandVerdict(needs_approval=sorted(reasons) or None)


# --------------------------------------------------------------------------- paths

_SECRET_NAMES = {".env", ".envrc", ".netrc", "id_rsa", "id_ed25519", "credentials", "state.db", "shared.db"}
_SECRET_DIRS = {".ssh", ".aws", ".gnupg", ".kube"}


@dataclass
class PathPolicy:
    """Confines file tools to a set of roots. Paths are resolved (symlinks followed) before the
    check, so `../` tricks and symlinks pointing outside a root are rejected."""

    roots: dict[str, Path]  # alias -> directory; the alias "" is the default (cwd) root

    def resolve(self, raw: str, *, for_write: bool = False) -> Path:
        if not raw or not str(raw).strip():
            raise PolicyError("empty path")
        raw = str(raw).strip()
        base = self.roots[""]
        # "shared/..." addresses the room's shared workspace when one is attached.
        head, _, rest = raw.replace("\\", "/").partition("/")
        if head in self.roots and head != "":
            base, raw = self.roots[head], rest or "."
        candidate = Path(os.path.expanduser(raw))
        if not candidate.is_absolute():
            candidate = base / candidate
        resolved = candidate.resolve()
        allowed = [r.resolve() for r in self.roots.values()]
        if not any(resolved == r or r in resolved.parents for r in allowed):
            roots = ", ".join(f"{k or '.'}={v}" for k, v in self.roots.items())
            raise PolicyError(f"path '{raw}' is outside the allowed workspace roots ({roots})")
        parts = set(resolved.parts)
        if parts & _SECRET_DIRS or resolved.name in _SECRET_NAMES or resolved.name.startswith(".env."):
            raise PolicyError(f"access to '{resolved.name}' is denied (credential/state file)")
        return resolved

    def display(self, path: Path) -> str:
        path = path.resolve()
        for alias, root in sorted(self.roots.items(), key=lambda kv: -len(str(kv[1]))):
            root = root.resolve()
            if path == root or root in path.parents:
                rel = path.relative_to(root).as_posix()
                if alias:
                    return f"{alias}/{rel}" if rel != "." else alias
                return rel or "."
        return str(path)


# --------------------------------------------------------------------------- untrusted content

_INJECTION = [
    (re.compile(r"\b(ignore|disregard|forget)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all)\b[^.\n]{0,20}\b(instructions?|prompts?|rules)", re.I),
     "asks to ignore prior instructions"),
    (re.compile(r"\b(you are now|act as|new instructions?:|system prompt:)", re.I), "tries to redefine the assistant's role"),
    (re.compile(r"<!--[^>]{0,400}\b(assistant|AI|agent|instruction|ignore|execute|run)\b[^>]{0,400}-->", re.I | re.S),
     "hidden HTML comment with instructions"),
    (re.compile(r"\b(cat|read|print|send|upload|post)\b[^\n]{0,60}(\.env\b|id_rsa|\.netrc|credentials|api[_ ]?key)", re.I),
     "asks to read or send secrets"),
    (re.compile(r"\b(curl|wget)\b[^\n]{0,120}\|\s*(ba)?sh\b", re.I), "pipes a download into a shell"),
    (re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069]"), "invisible Unicode control characters"),
]


def scan_untrusted(text: str) -> list[str]:
    """Heuristic prompt-injection scan for content that comes from outside (web pages, search results).
    It flags; it does not block — the agent is told the content is data, not instructions."""
    return sorted({desc for rx, desc in _INJECTION if rx.search(text or "")})
