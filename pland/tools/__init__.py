"""Built-in tools. Toolsets: files, code, web, git, memory, plan, hitl, delegation, team — chosen per profile —
and platform (facts about PlanD itself), which every agent has."""

_loaded = False


def load_builtin_tools() -> None:
    global _loaded
    if _loaded:
        return
    from . import about, code, files, git, hitl_tools, memory_tools, plan, team, web  # noqa: F401  (registration side effects)

    _loaded = True
