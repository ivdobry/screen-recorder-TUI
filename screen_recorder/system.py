"""Everything that talks to other programs: compositor, audio, files, desktop."""

import asyncio
import json
import shutil
from pathlib import Path


def available(program: str) -> bool:
    return shutil.which(program) is not None


async def run(*cmd: str) -> tuple[int, str]:
    """Run a command and return (exit code, stdout)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode().strip()


def spawn(*cmd: str) -> None:
    """Start a program (player, file manager) without waiting for it or tying it to the TUI."""
    asyncio.get_running_loop().create_task(
        asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    )


# ---- recording --------------------------------------------------------------


async def start_wf_recorder(cmd: list[str]) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,  # keep it from reading the TUI's keystrokes
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )


async def focused_output() -> str | None:
    """Name of the focused monitor (niri / Hyprland), or None to let wf-recorder pick."""
    if available("niri"):
        code, out = await run("niri", "msg", "--json", "focused-output")
        if code == 0:
            return json.loads(out)["name"]
    if available("hyprctl"):
        code, out = await run("hyprctl", "-j", "monitors")
        if code == 0:
            return next((m["name"] for m in json.loads(out) if m["focused"]), None)
    return None


async def select_region() -> str | None:
    """Let the user drag an area with slurp; None if cancelled."""
    code, geometry = await run("slurp")
    return geometry if code == 0 and geometry else None


async def system_audio_device() -> str | None:
    """Monitor source of the current default output, i.e. "what you hear"."""
    if not available("pactl"):
        return None
    code, sink = await run("pactl", "get-default-sink")
    return f"{sink}.monitor" if code == 0 and sink else None


async def video_length(path: Path) -> str:
    if not available("ffprobe"):
        return "—"
    code, out = await run(
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)
    )
    try:
        seconds = round(float(out))
    except ValueError:
        return "—"
    return f"{seconds // 60}:{seconds % 60:02d}"


# ---- desktop ----------------------------------------------------------------


def notify(title: str, body: str, timeout_ms: int | None = None) -> None:
    if available("notify-send"):
        timeout = ["-t", str(timeout_ms)] if timeout_ms else []
        spawn("notify-send", *timeout, title, body)


async def ask_save_path(suggested: Path) -> Path | None:
    """Native "Save as" dialog (zenity); None if cancelled."""
    code, chosen = await run(
        "zenity", "--file-selection", "--save",
        "--title=Save recording as", f"--filename={suggested}",
    )
    return Path(chosen) if code == 0 and chosen else None


def open_with_default_app(path: Path) -> bool:
    if not available("xdg-open"):
        return False
    spawn("xdg-open", str(path))
    return True


async def show_in_file_manager(path: Path) -> bool:
    """Open the folder with the file selected; fall back to just opening the folder."""
    if available("gdbus"):
        code, _ = await run(
            "gdbus", "call", "--session",
            "--dest", "org.freedesktop.FileManager1",
            "--object-path", "/org/freedesktop/FileManager1",
            "--method", "org.freedesktop.FileManager1.ShowItems",
            f"['{path.as_uri()}']", "",
        )
        if code == 0:
            return True
    return open_with_default_app(path.parent)


async def copy_to_clipboard(text: str) -> bool:
    """Copy with wl-copy; False if it isn't installed (the caller can fall back)."""
    if not available("wl-copy"):
        return False
    await run("wl-copy", "--", text)
    return True


def can_trash() -> bool:
    return available("gio")


async def delete(path: Path) -> bool:
    """Move to the Trash when possible, otherwise delete permanently."""
    if can_trash():
        code, _ = await run("gio", "trash", str(path))
        return code == 0
    try:
        path.unlink()
    except OSError:
        return False
    return True
