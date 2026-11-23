"""Built-in tools. Toolsets: files, code, web, git, memory, plan, hitl, delegation, team."""

_loaded = False


def load_builtin_tools() -> None:
    global _loaded
    if _loaded:
        return
    from . import code, files, git, hitl_tools, memory_tools, plan, team, web  # noqa: F401  (registration side effects)

    _loaded = True
