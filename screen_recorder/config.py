"""Settings, stored as JSON in ~/.config/screen-recorder-tui/config.json."""

import json
from pathlib import Path

CONFIG_FILE = Path.home() / ".config" / "screen-recorder-tui" / "config.json"

DEFAULT_FOLDER = Path.home() / "Videos"
AUDIO_SOURCES = {"off": "Off", "mic": "Microphone", "system": "System sound"}
COUNTDOWNS = (0, 3, 5, 10)  # seconds; 0 = start straight away
DEFAULT_COUNTDOWN = 3
MAX_RECENT = 20


def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_config(**changes) -> None:
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps({**load_config(), **changes}, indent=2))
    except OSError:
        pass  # not worth crashing the recorder over


def audio_source(settings: dict) -> str:
    # Older configs stored a plain on/off "audio" flag, which meant the mic
    source = settings.get("audio_source") or ("mic" if settings.get("audio") else "off")
    return source if source in AUDIO_SOURCES else "off"


def countdown(settings: dict) -> int:
    value = settings.get("countdown", DEFAULT_COUNTDOWN)
    return value if value in COUNTDOWNS else DEFAULT_COUNTDOWN


# ---- recent recordings ------------------------------------------------------


def recent_recordings() -> list[Path]:
    """Recordings made with the app, newest first, skipping files that are gone."""
    paths = [Path(p) for p in load_config().get("recent", [])]
    existing = [p for p in paths if p.exists()]
    if len(existing) != len(paths):
        _set_recent(existing)
    return existing


def _set_recent(paths: list[Path]) -> None:
    save_config(recent=[str(p) for p in paths[:MAX_RECENT]])


def remember_recording(path: Path) -> None:
    _set_recent([path, *(p for p in recent_recordings() if p != path)])


def forget_recording(path: Path) -> None:
    _set_recent([p for p in recent_recordings() if p != path])


def rename_recording(old: Path, new: Path, history: list[Path]) -> None:
    """Swap old for new in the list, keeping its place. `history` is the list from
    before the file was renamed (afterwards `old` no longer exists and is pruned)."""
    _set_recent([new if p == old else p for p in history])
