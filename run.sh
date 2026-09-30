#!/usr/bin/env bash
exec "$(dirname "$(readlink -f "$0")")/.venv/bin/python" "$(dirname "$(readlink -f "$0")")/recorder.py" "$@"
