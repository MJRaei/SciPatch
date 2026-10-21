#!/bin/sh
# Install Motel on macOS or Linux.
#
#   ./install.sh                     install from this copy of the repository
#   MOTEL_SOURCE=<spec> sh install.sh  install from a git URL, a folder, or PyPI ("motel")
#
# Options (environment variables):
#   MOTEL_NO_MODIFY_PATH=1   don't add uv's tool folder to your shell configuration
#   MOTEL_NO_SETUP=1         don't start 'motel setup' afterwards
set -eu

say() { printf '%s\n' "$*"; }

# 1. uv: installs Python and builds each tool's environment.
if ! command -v uv >/dev/null 2>&1; then
    say "==> Installing uv (it manages Python for Motel and its tools)..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH="${MOTEL_NO_MODIFY_PATH:-}" sh
    else
        wget -qO- https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH="${MOTEL_NO_MODIFY_PATH:-}" sh
    fi
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi

# 2. Motel itself, in its own isolated environment.
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
if [ -n "${MOTEL_SOURCE:-}" ]; then
    source="$MOTEL_SOURCE"
elif [ -f "$script_dir/pyproject.toml" ] && grep -q '^name = "motel"' "$script_dir/pyproject.toml"; then
    source="$script_dir"
else
    source="motel"
fi
say "==> Installing Motel from $source"
uv tool install --force --python 3.12 "$source"
if [ -z "${MOTEL_NO_MODIFY_PATH:-}" ]; then
    uv tool update-shell >/dev/null 2>&1 || true
fi

motel="$(uv tool dir --bin)/motel"
say ""
say "==> Motel $("$motel" --version | cut -d' ' -f2) is installed at $motel"

# 3. Guided setup: checks requirements and connects your AI apps.
if [ -z "${MOTEL_NO_SETUP:-}" ]; then
    say ""
    if [ -t 0 ]; then
        "$motel" setup || true
    else
        # Piped installs have no keyboard input; setup must run in a terminal.
        say "Next, run 'motel setup' in a new terminal."
    fi
fi
say ""
say "Open a new terminal window to use the 'motel' command."
