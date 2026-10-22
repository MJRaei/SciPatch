#!/bin/sh
# Install SciPatch on macOS or Linux.
#
#   ./install.sh                          install from this copy of the repository
#   SCIPATCH_SOURCE=<spec> sh install.sh  install from a git URL, a folder, or PyPI ("scipatch")
#
# Options (environment variables):
#   SCIPATCH_NO_MODIFY_PATH=1   don't add uv's tool folder to your shell configuration
#   SCIPATCH_NO_SETUP=1         don't start 'scipatch setup' afterwards
set -eu

say() { printf '%s\n' "$*"; }

# 1. uv: installs Python and builds each tool's environment.
if ! command -v uv >/dev/null 2>&1; then
    say "==> Installing uv (it manages Python for SciPatch and its tools)..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH="${SCIPATCH_NO_MODIFY_PATH:-}" sh
    else
        wget -qO- https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH="${SCIPATCH_NO_MODIFY_PATH:-}" sh
    fi
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi

# 2. SciPatch itself, in its own isolated environment.
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
if [ -n "${SCIPATCH_SOURCE:-}" ]; then
    source="$SCIPATCH_SOURCE"
elif [ -f "$script_dir/pyproject.toml" ] && grep -q '^name = "scipatch"' "$script_dir/pyproject.toml"; then
    source="$script_dir"
else
    source="scipatch"
fi
say "==> Installing SciPatch from $source"
uv tool install --force --python 3.12 "$source"
if [ -z "${SCIPATCH_NO_MODIFY_PATH:-}" ]; then
    uv tool update-shell >/dev/null 2>&1 || true
fi

scipatch="$(uv tool dir --bin)/scipatch"
say ""
say "==> SciPatch $("$scipatch" --version | cut -d' ' -f2) is installed at $scipatch"

# 3. Guided setup: checks requirements and connects your AI apps.
if [ -z "${SCIPATCH_NO_SETUP:-}" ]; then
    say ""
    if [ -t 0 ]; then
        "$scipatch" setup || true
    else
        # Piped installs have no keyboard input; setup must run in a terminal.
        say "Next, run 'scipatch setup' in a new terminal."
    fi
fi
say ""
say "Open a new terminal window to use the 'scipatch' command."
