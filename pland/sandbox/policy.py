"""Static safety policy: command classification and file-path confinement.

The dangerous-command patterns are adapted from Hermes Agent (MIT License, Copyright (c) 2025 Nous Research;
see LICENSE).
"""

from __future__ import annotations

import os
import re
import shlex
import tokenize
from dataclasses import dataclass
from io import StringIO
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
    (r">\s*/etc/", "overwrite a system config file"),
    (r"\b(cp|mv|tee|install)\b[^\n]*\s/etc/", "write into /etc"),
    (r"(~|\$HOME|/Users/[^/\s]+|/home/[^/\s]+)/\.(ssh|aws|kube|gnupg|netrc|config/gh)\b", "touch credential files"),
    (r"\bdocker\s+(rm|rmi|kill|stop|system\s+prune|volume\s+rm)\b", "docker lifecycle / deletion"),
    (r"\bpip\s+install\b[^\n]*--break-system-packages", "modify the system Python"),
    (r"\bbrew\s+(uninstall|remove)\b", "uninstall system packages"),
    (r"\bnpm\s+(publish|unpublish)\b", "publish a package"),
]

# Content-level shapes a verb list misses: secrets in upload bodies, and
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
_SQL_DANGEROUS = [
    (re.compile(r"\bDROP\s+(TABLE|DATABASE)\b", _F), "SQL DROP"),
    (re.compile(r"\bDELETE\s+FROM\b(?![^\n]*\bWHERE\b)", _F), "SQL DELETE without WHERE"),
    (re.compile(r"\bTRUNCATE\s+TABLE\b", _F), "SQL TRUNCATE"),
]

# A top-level Python command reading a literal heredoc, as used for short inline scripts.
# Leave more general shell syntax to the original conservative text scan.
_PYTHON_HEREDOC = re.compile(
    r"""^[ \t]*(?:cd[ \t]+(?:'[^'\n]+'|"[^"\\$\x60\n]+"|[\w./~-]+)[ \t]+&&[ \t]+)?"""
    r"""python(?:3(?:\.\d+)?)?[ \t]+-[ \t]+<<[ \t]*(?P<quote>['"])(?P<end>[a-zA-Z_]\w*)"""
    r"""(?P=quote)[ \t]*\n"""
)

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


def _without_python_comments(source: str) -> str:
    lines = source.split("\n")
    try:
        for token in tokenize.generate_tokens(StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                row, start = token.start
                _, end = token.end
                line = lines[row - 1]
                lines[row - 1] = line[:start] + " " * (end - start) + line[end:]
    except (tokenize.TokenError, SyntaxError):
        return source
    return "\n".join(lines)


# --------------------------------------------------------------------------- git push detection
# `git push` is matched on tokens, not text, so options between `git` and the subcommand (`git -c k=v push`,
# `git -C dir push`, `git --git-dir=… push`) and the plumbing that pushes (`send-pack`, `http-push`, the remote
# helpers `remote-https`, `remote-ext`, …) are caught too. Still a rule match: it is the approval trigger for shells
# without an OS sandbox, not a boundary (a subcommand hidden in a variable or alias defined elsewhere is not seen).
_PUSH_REASON = "push to a remote repository"
_GIT_OPTS_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix",
                      "--exec-path", "--attr-source", "--list-cmds"}
_PUSH_SUBCOMMANDS = {"push", "send-pack", "http-push"}
_SHELL_PUNCT = set(";&|()<>")


def _shell_tokens(text: str) -> list[str]:
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex)
    except ValueError:  # unbalanced quotes: fall back to a rough split
        return [t for t in re.split(r"[\s'\"]+|([;&|()<>])", text) if t]


def _is_push_subcommand(sub: str, rest: list[str]) -> bool:
    if sub in _PUSH_SUBCOMMANDS or sub.startswith("remote-"):
        return True
    if sub in {"subtree", "lfs"} and "push" in rest[:3]:
        return True
    return "$" in sub or "`" in sub  # subcommand computed at run time: cannot tell, so ask


def _git_pushes(text: str, depth: int = 0) -> bool:
    """True when a shell command (or a string inside it, e.g. `sh -c '…'`) runs a git command that pushes."""
    if depth > 3:
        return False
    tokens = _shell_tokens(text)
    for i, raw in enumerate(tokens):
        tok = raw.strip("`$({}")
        if depth < 3 and any(c.isspace() for c in raw) and _git_pushes(raw, depth + 1):
            return True  # quoted script: sh -c "git -C x push", eval '…', submodule foreach '…'
        base = tok.rsplit("/", 1)[-1]
        if base.startswith("git-") and _is_push_subcommand(base[4:], tokens[i + 1:i + 4]):
            return True  # direct helper binary: git-push, git-send-pack, git-remote-https …
        if base != "git":
            continue
        j = i + 1
        while j < len(tokens) and tokens[j].startswith("-") and tokens[j] not in _SHELL_PUNCT:
            opt = tokens[j]
            if opt in _GIT_OPTS_WITH_ARG:
                value = tokens[j + 1] if j + 1 < len(tokens) else ""
                if opt == "-c" and value.lower().startswith("alias.") and "=" in value:
                    body = value.split("=", 1)[1]
                    if _git_pushes(body[1:] if body.startswith("!") else f"git {body}", depth + 1):
                        return True  # git -c alias.p=push p
                if opt == "--config-env" and value.lower().startswith("alias."):
                    return True  # alias body comes from the environment: cannot tell
                j += 2
            else:
                if opt.startswith("--config-env=alias."):
                    return True
                j += 1
        if j < len(tokens) and tokens[j] not in _SHELL_PUNCT and _is_push_subcommand(tokens[j], tokens[j + 1:j + 4]):
            return True
    return False


def _check_command(command: str, sql_source: str) -> CommandVerdict:
    text = command.replace("\\\n", " ")
    for rx, desc in _HARDLINE:
        if rx.search(text):
            return CommandVerdict(blocked=desc)
    reasons = {desc for rx, desc in _DANGEROUS if rx.search(text)}
    if "git" in text and _git_pushes(text):
        reasons.add(_PUSH_REASON)
    sql_source = sql_source.replace("\\\n", " ")
    reasons.update(desc for rx, desc in _SQL_DANGEROUS if rx.search(sql_source))
    return CommandVerdict(needs_approval=sorted(reasons) or None)


def check_command(command: str) -> CommandVerdict:
    header = _PYTHON_HEREDOC.match(command)
    if header:
        body = command[header.end():]
        end = re.search(rf"(?m)^{re.escape(header['end'])}$", body)
        if end:
            sql_source = command[:header.end()] + _without_python_comments(body[:end.start()]) + body[end.start():]
            return _check_command(command, sql_source)
    return _check_command(command, command)


def scan_python(code: str) -> CommandVerdict:
    """Python can bypass shell patterns, so scan the source and any shell strings embedded in it."""
    hard = _check_command(code, _without_python_comments(code))
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
