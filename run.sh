#!/usr/bin/env bash
dir="$(dirname "$(readlink -f "$0")")"
PYTHONPATH="$dir${PYTHONPATH:+:$PYTHONPATH}" exec "$dir/.venv/bin/python" -m screen_recorder "$@"
