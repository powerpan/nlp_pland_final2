#!/usr/bin/env bash
# Install PlanD so that `pland` works from any folder:
#
#   bash scripts/install.sh            # from a clone of the repository
#
# It creates .venv (Python 3.10+) if needed, installs the package in editable mode, and writes a small
# launcher to ~/.local/bin/pland (override with PLAND_BIN_DIR). The launcher runs the venv's Python in
# isolated mode (-I), so the folder you start it from cannot shadow PlanD's modules. Your shell config is
# never edited; if the folder is not on PATH the script prints the line to add.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${PLAND_BIN_DIR:-$HOME/.local/bin}"
VENV_PY="$REPO/.venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
  PY=""
  for c in "${PLAND_PYTHON:-}" python3.13 python3.12 python3.11 python3.10 python3; do
    [ -n "$c" ] && command -v "$c" >/dev/null 2>&1 || continue
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then PY="$c"; break; fi
  done
  if [ -z "$PY" ]; then
    echo "PlanD needs Python 3.10 or newer (e.g. brew install python@3.11), or set PLAND_PYTHON." >&2
    exit 1
  fi
  echo "creating $REPO/.venv with $("$PY" --version)"
  "$PY" -m venv "$REPO/.venv"
fi

if [ "${1:-}" = "--reinstall" ] || ! "$VENV_PY" -I -c 'import pland' >/dev/null 2>&1; then
  echo "installing PlanD and its dependencies into .venv"
  "$VENV_PY" -m pip install --quiet --upgrade pip
  "$VENV_PY" -m pip install --quiet -e "$REPO"
fi

mkdir -p "$BIN_DIR"
LAUNCHER="$BIN_DIR/pland"
QUOTED_REPO=$(printf "'%s'" "$(printf '%s' "$REPO" | sed "s/'/'\\\\''/g")")
cat > "$LAUNCHER" <<EOF
#!/bin/sh
# PlanD launcher, written by scripts/install.sh — runs PlanD from any folder.
PLAND_REPO=$QUOTED_REPO
if [ ! -x "\$PLAND_REPO/.venv/bin/python" ]; then
  echo "pland: no installation at \$PLAND_REPO (moved or deleted?); run scripts/install.sh again." >&2
  exit 127
fi
exec "\$PLAND_REPO/.venv/bin/python" -I -m pland.cli "\$@"
EOF
chmod +x "$LAUNCHER"
echo "launcher: $LAUNCHER"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo
     echo "$BIN_DIR is not on your PATH. Add it, e.g.:"
     echo "  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.zshrc && source ~/.zshrc" ;;
esac

echo
echo "Done. From any folder:"
echo "  pland              chat with the default agent"
echo "  pland desktop      open the web UI (Bot Mode) in its own window"
echo "  pland setup        API key, model, thinking intensity, sandbox, approvals"
echo "  pland team apply requirements-team   add the sample bot team"
