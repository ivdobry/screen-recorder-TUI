"""Small helpers for paths, names and sizes."""

from datetime import datetime
from pathlib import Path

from textual.suggester import Suggester


def tilde(path: Path) -> str:
    """Show paths under the home folder as ~/…"""
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def default_name() -> str:
    return f"recording-{datetime.now():%Y%m%d-%H%M%S}.mp4"


def unique_path(path: Path) -> Path:
    """Add -1, -2, … to the name so an existing recording is never overwritten."""
    candidate, n = path, 1
    while candidate.exists():
        candidate = path.with_stem(f"{path.stem}-{n}")
        n += 1
    return candidate


def human_size(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


class DirectorySuggester(Suggester):
    """Inline completion of directory names (accept with →)."""

    def __init__(self) -> None:
        super().__init__(use_cache=False, case_sensitive=True)

    async def get_suggestion(self, value: str) -> str | None:
        head, _, prefix = value.rpartition("/")
        parent = Path(head or "/").expanduser() if "/" in value else Path.cwd()
        try:
            matches = sorted(
                d.name for d in parent.iterdir()
                if d.is_dir() and d.name.startswith(prefix) and not d.name.startswith(".")
            )
        except OSError:
            return None
        if not matches or matches[0] == prefix:
            return None
        return f"{head}/{matches[0]}" if "/" in value else matches[0]
