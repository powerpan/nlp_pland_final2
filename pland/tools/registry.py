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
    return [t for t in TOOLS.values() if t.toolset in toolsets and t.name not in exclude]


def execute(t: Tool, ctx: ToolContext, args: dict[str, Any]) -> str:
    try:
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
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, indent=1, default=str)
