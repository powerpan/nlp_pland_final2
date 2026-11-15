"""Built-in file, code, and memory tools."""

_loaded = False


def load_builtin_tools() -> None:
    global _loaded
    if _loaded:
        return
    from . import code, files, memory_tools  # noqa: F401  (registration side effects)

    _loaded = True
