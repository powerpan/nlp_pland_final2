"""Tool registry and the per-call execution context."""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..agent import Agent
    from ..approvals import ApprovalGate
    from ..config import AgentSettings
    from ..hitl import HITLChannel
    from ..profiles import Profile
    from ..runtime import Runtime
    from ..sandbox import Backend, PathPolicy


class ToolError(Exception):
    """An error the model should see and can recover from."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[["ToolContext", dict[str, Any]], Any]
    toolset: str

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


@dataclass
class ToolContext:
    runtime: "Runtime"
    agent: "Agent"
    profile: "Profile"
    settings: "AgentSettings"
    session_id: str
    run_id: str
    backend: "Backend"
    paths: "PathPolicy"
    hitl: "HITLChannel"
    approvals: "ApprovalGate"
    room_id: str | None = None
    depth: int = 0
    chain: list[str] = field(default_factory=list)
    tool_call_id: str | None = None

    @property
    def workspace(self) -> Path:
        return self.paths.roots[""]

    @property
    def mounts(self) -> dict[str, Path]:
        return {k: v for k, v in self.paths.roots.items() if k}

    def emit(self, type: str, **data: Any) -> None:
        self.runtime.bus.publish(type, profile=self.profile.name, session_id=self.session_id, room_id=self.room_id,
                                 run_id=self.run_id, **data)

    def require_approval(self, category: str, summary: str, detail: str = "") -> None:
        decision = self.approvals.require(category, summary, detail)
        self.emit("approval.decided", category=category, summary=summary, allowed=decision.allowed, reason=decision.reason)
        if not decision.allowed:
            raise ToolError(f"Operation not permitted — {decision.reason}. Do not retry the same operation; "
                            f"choose another approach or explain the situation to the user.")


TOOLS: dict[str, Tool] = {}
# Every agent has this toolset whatever its profile's `toolsets` says: it is how an agent answers questions about
# the platform and its own setup (pland/handbook), and it is read-only.
ALWAYS_ON = "platform"


def tool(name: str, description: str, parameters: dict[str, Any], toolset: str):
    def deco(fn):
        TOOLS[name] = Tool(name=name, description=description.strip(), parameters=parameters, handler=fn, toolset=toolset)
        return fn

    return deco


def obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


def select_tools(toolsets: list[str], exclude: set[str] | None = None) -> list[Tool]:
    from . import load_builtin_tools

    load_builtin_tools()
    exclude = exclude or set()
    wanted = {*toolsets, ALWAYS_ON}
    return [t for t in TOOLS.values() if t.toolset in wanted and t.name not in exclude]


_COERCE = {"integer": int, "number": float}


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Model-produced arguments are untrusted: drop unknown keys, coerce scalar types, enforce required."""
    props = schema.get("properties", {})
    notes: list[str] = []
    clean: dict[str, Any] = {}
    for key, val in args.items():
        spec = props.get(key)
        if spec is None:
            notes.append(f"ignored unknown argument '{key}'")
            continue
        typ = spec.get("type")
        if typ in _COERCE and isinstance(val, str):
            try:
                val = _COERCE[typ](val.strip())
            except ValueError:
                raise ToolError(f"argument '{key}' must be a {typ}")
        elif typ == "boolean" and isinstance(val, str):
            val = val.strip().lower() in {"true", "1", "yes"}
        elif typ == "array" and isinstance(val, str):
            try:
                parsed = json.loads(val)
                val = parsed if isinstance(parsed, list) else [val]
            except json.JSONDecodeError:
                val = [val]
        elif typ == "string" and val is not None and not isinstance(val, str):
            val = json.dumps(val, ensure_ascii=False) if isinstance(val, (dict, list)) else str(val)
        if "enum" in spec and val not in spec["enum"]:
            raise ToolError(f"argument '{key}' must be one of {spec['enum']}")
        clean[key] = val
    missing = [k for k in schema.get("required", []) if clean.get(k) in (None, "")]
    if missing:
        raise ToolError(f"missing required argument(s): {', '.join(missing)}")
    return clean, notes


def execute(t: Tool, ctx: ToolContext, args: dict[str, Any]) -> str:
    notes: list[str] = []
    try:
        args, notes = validate_args(t.parameters, args)
        result = t.handler(ctx, args)
    except ToolError as exc:
        return f"ERROR: {exc}"
    except PermissionError as exc:
        return f"ERROR (permission): {exc}"
    except (KeyError, ValueError, TypeError, FileNotFoundError, IsADirectoryError, NotADirectoryError) as exc:
        return f"ERROR: {type(exc).__name__}: {exc}"
    except Exception as exc:  # unexpected bug inside a tool: report it to the model, keep the run alive
        tb = traceback.format_exc(limit=3)
        return f"ERROR: tool '{t.name}' crashed: {type(exc).__name__}: {exc}\n{tb}"
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=1, default=str)
    return ("NOTE: " + "; ".join(notes) + "\n" + text) if notes else text
