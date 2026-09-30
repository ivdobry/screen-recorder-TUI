#!/usr/bin/env bash
# Set up the virtualenv and put a `screen-recorder` command in ~/.local/bin
set -euo pipefail

dir="$(dirname "$(readlink -f "$0")")"
bin="${BIN_DIR:-$HOME/.local/bin}"
name="${1:-screen-recorder}"

if [ ! -x "$dir/.venv/bin/python" ]; then
    echo "Creating virtualenv…"
    python -m venv "$dir/.venv"
fi
"$dir/.venv/bin/pip" install -q -r "$dir/requirements.txt"

mkdir -p "$bin"
ln -sf "$dir/run.sh" "$bin/$name"
echo "Installed: $bin/$name -> $dir/run.sh"

case ":$PATH:" in
    *":$bin:"*) echo "Run it with: $name" ;;
    *) echo "Note: $bin is not in your PATH. Add this to your shell config:"
       echo "  export PATH=\"$bin:\$PATH\"" ;;
esac
