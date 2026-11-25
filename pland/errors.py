"""Exception types shared by the stores and the HTTP API.

`NotFound` is what a store lookup raises when the object asked for does not exist (a profile, session, room, HITL
request or board task). It subclasses `KeyError`, so callers that catch `KeyError` (the CLI, the tools, delegation)
keep working, while the API maps only `NotFound` to 404: any other `KeyError` is a bug and surfaces as a 500.
"""

from __future__ import annotations


class NotFound(KeyError):
    """A looked-up object does not exist; `args[0]` is the message (or the bare id). Behaves like `KeyError`
    otherwise, `str()` included, so messages built from it stay what they were."""
