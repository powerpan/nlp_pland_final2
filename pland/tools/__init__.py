"""Built-in tools. Toolsets: files, code, web, git, memory, plan, hitl."""

from importlib import import_module
from importlib.util import find_spec


def load_builtin_tools() -> None:
    from . import code, files, git, memory_tools, web  # noqa: F401  (registration side effects)

    # These modules become available as subsequent packages are applied.
    for name in ('plan', 'hitl_tools'):
        module = f"{__package__}.{name}"
        if find_spec(module) is not None:
            import_module(module)
