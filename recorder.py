"""TUI front-end for wf-recorder: record full screen or a region, then stop."""

import asyncio
import json
import shutil
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets import (
    Button, DirectoryTree, Footer, Header, Input, Label, RichLog, Static, Switch,
)

OUTPUT_DIR = Path.home() / "Videos"
# --no-zenity: always use the in-terminal folder browser (handy for testing it)
USE_ZENITY = "--no-zenity" not in sys.argv
CONFIG_FILE = Path.home() / ".config" / "screen-recorder-tui" / "config.json"


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


async def focused_output() -> str | None:
    """Name of the focused monitor (niri / Hyprland), or None to let wf-recorder pick."""
    if shutil.which("niri"):
        code, out = await run("niri", "msg", "--json", "focused-output")
        if code == 0:
            return json.loads(out)["name"]
    if shutil.which("hyprctl"):
        code, out = await run("hyprctl", "-j", "monitors")
        if code == 0:
            return next((m["name"] for m in json.loads(out) if m["focused"]), None)
    return None


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


def unique_path(path: Path) -> Path:
    """Add -1, -2, … to the name so an existing recording is never overwritten."""
    candidate, n = path, 1
    while candidate.exists():
        candidate = path.with_stem(f"{path.stem}-{n}")
        n += 1
    return candidate


class FolderPicker(ModalScreen[Path | None]):
    """In-terminal folder browser, used when no graphical file dialog is available."""

    CSS = """
    FolderPicker { align: center middle; }
    #picker { width: 80%; height: 80%; border: round $accent; background: $surface; padding: 0 1; }
    #picker DirectoryTree { height: 1fr; }
    #picker Horizontal { height: auto; align-horizontal: right; }
    #picker Button { margin: 0 1; }
    """
    BINDINGS = [("escape", "dismiss(None)", "Cancel")]

    class FoldersOnly(DirectoryTree):
        def filter_paths(self, paths):
            return [p for p in paths if p.is_dir() and not p.name.startswith(".")]

    def __init__(self, start: Path) -> None:
        super().__init__()
        self.selected = start

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Label(f"Choose a folder: [cyan]{self.selected}[/]", id="current")
            yield self.FoldersOnly(Path.home(), id="tree")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Select", id="select", variant="primary")

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self.selected = event.path
        self.query_one("#current", Label).update(f"Choose a folder: [cyan]{event.path}[/]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self.selected if event.button.id == "select" else None)


class Recorder(App):
    TITLE = "Screen Recorder"
    CSS = """
    Screen { align-horizontal: center; }
    #main { width: 100%; max-width: 110; height: 1fr; padding: 1 2 0 2; }

    .card {
        border: round $primary 40%;
        border-title-color: $text-muted;
        border-title-style: bold;
        padding: 0 1;
        margin-bottom: 1;
        height: auto;
    }

    #status-card { padding: 0 2; }
    #status { text-style: bold; color: $success; }
    #status-hint { color: $text-muted; }
    #status-card.recording { border: round $error; background: $error 10%; }
    #status-card.recording #status { color: $error; }

    #buttons { height: auto; margin-bottom: 1; }
    #buttons Button { width: 1fr; margin: 0 1 0 0; }
    #buttons Button:last-of-type { margin-right: 0; }
    Button:focus { text-style: bold; }

    /* label | field | button — every row shares the same columns */
    #output {
        layout: grid;
        grid-size: 3;
        grid-columns: 8 1fr 16;
        grid-rows: 3;
        grid-gutter: 1 1;
        padding: 1 2 0 2;
    }
    #output > Label { height: 3; content-align: left middle; color: $text-muted; }
    #output Input, #browse { width: 100%; }
    #name, #audio-row { column-span: 2; }
    #audio-row { height: 3; }
    #audio-row Label { height: 3; content-align: left middle; padding: 0 1; }

    #activity { height: 1fr; min-height: 6; margin-bottom: 0; }
    #activity RichLog {
        background: transparent;
        scrollbar-size-vertical: 1;
        scrollbar-background: $surface;
        scrollbar-color: $primary 40%;
    }
    """
    BINDINGS = [
        ("f", "full", "Full screen"),
        ("s", "region", "Section"),
        ("x", "stop", "Stop"),
        ("a", "toggle_audio", "Audio"),
        ("b", "browse", "Browse"),
        ("q", "quit", "Quit"),
    ]

    proc: asyncio.subprocess.Process | None = None
    started_at = 0.0
    current_file: Path | None = None

    def compose(self) -> ComposeResult:
        config = load_config()
        yield Header(icon="◉")
        with Vertical(id="main"):
            with Vertical(id="status-card", classes="card") as card:
                card.border_title = "Status"
                yield Static(id="status")
                yield Static(id="status-hint")
            with Horizontal(id="buttons"):
                yield Button("▣  Full screen  [dim]F[/]", id="full", variant="primary")
                yield Button("▢  Section  [dim]S[/]", id="region", variant="primary")
                yield Button("■  Stop  [dim]X[/]", id="stop", variant="error", disabled=True)
            with Grid(id="output", classes="card") as card:
                card.border_title = "Output"
                yield Label("Folder")
                yield Input(
                    config.get("folder", self.tilde(OUTPUT_DIR)),
                    id="dir",
                    suggester=DirectorySuggester(),
                )
                yield Button("Browse  [dim]B[/]", id="browse")
                yield Label("Name")
                yield Input(placeholder="recording-<date>-<time>  (default)", id="name")
                yield Label("Audio")
                with Horizontal(id="audio-row"):
                    yield Switch(config.get("audio", False), id="audio")
                    yield Label("Record audio  [dim]A[/]")
            with Vertical(id="activity", classes="card") as card:
                card.border_title = "Activity"
                yield RichLog(markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        theme = load_config().get("theme")
        if theme in self.available_themes:
            self.theme = theme
        # Remember the theme picked from the command palette (Ctrl+P → "Change theme")
        self.watch(self, "theme", lambda theme: save_config(theme=theme), init=False)
        if not shutil.which("wf-recorder"):
            self.log_line("[red]wf-recorder not found in PATH[/]")
        self.log_line("[dim]Tip: Enter or Esc leaves a text field so the shortcuts work again.[/]")
        self.set_recording(False)
        self.set_focus(None)  # nothing focused, so the single-key shortcuts work at once
        self.set_interval(1, self.tick)

    # ---- UI helpers -------------------------------------------------------

    @staticmethod
    def tilde(path: Path) -> str:
        try:
            return "~/" + str(path.relative_to(Path.home()))
        except ValueError:
            return str(path)

    def on_input_changed(self, event: Input.Changed) -> None:
        # Only remember real folders, not half-typed paths
        if event.input.id == "dir" and Path(event.value.strip()).expanduser().is_dir():
            save_config(folder=event.value.strip())

    def on_switch_changed(self, event: Switch.Changed) -> None:
        save_config(audio=event.value)

    def on_input_submitted(self) -> None:
        self.set_focus(None)  # give the keys back to the F/S/X shortcuts

    def on_key(self, event) -> None:
        if event.key == "escape" and isinstance(self.focused, Input):
            self.set_focus(None)

    def target_file(self) -> Path:
        folder = Path(self.query_one("#dir", Input).value.strip() or OUTPUT_DIR).expanduser()
        name = self.query_one("#name", Input).value.strip()
        name = name or f"recording-{datetime.now():%Y%m%d-%H%M%S}"
        if not Path(name).suffix:
            name += ".mp4"
        return unique_path(folder / name)

    def log_line(self, text: str) -> None:
        self.query_one(RichLog).write(text)

    def set_recording(self, recording: bool) -> None:
        self.query_one("#full", Button).disabled = recording
        self.query_one("#region", Button).disabled = recording
        self.query_one("#stop", Button).disabled = not recording
        self.query_one("#audio", Switch).disabled = recording
        self.query_one("#dir", Input).disabled = recording
        self.query_one("#name", Input).disabled = recording
        self.query_one("#browse", Button).disabled = recording
        self.query_one("#status-card").set_class(recording, "recording")
        if not recording:
            self.query_one("#status", Static).update("○  READY")
            self.query_one("#status-hint", Static).update(
                "Press F for full screen or S to record a section"
            )

    def tick(self) -> None:
        if self.proc:
            elapsed = int(time.monotonic() - self.started_at)
            dot = "●" if elapsed % 2 == 0 else "○"  # blink
            self.query_one("#status", Static).update(f"{dot}  REC  {elapsed // 60:02d}:{elapsed % 60:02d}")
            self.query_one("#status-hint", Static).update(f"→ {self.tilde(self.current_file)}")

    # ---- actions ----------------------------------------------------------

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        await self.run_action(event.button.id)

    def action_toggle_audio(self) -> None:
        switch = self.query_one("#audio", Switch)
        if not switch.disabled:
            switch.toggle()

    async def action_browse(self) -> None:
        if self.proc:
            return
        folder_input = self.query_one("#dir", Input)
        name_input = self.query_one("#name", Input)
        folder = Path(folder_input.value.strip() or OUTPUT_DIR).expanduser()
        if not folder.is_dir():
            folder = Path.home()

        if USE_ZENITY and shutil.which("zenity"):
            # Native "Save as" dialog: pick the folder and the file name in one go
            default = f"recording-{datetime.now():%Y%m%d-%H%M%S}.mp4"
            name = name_input.value.strip() or default
            code, chosen = await run(
                "zenity", "--file-selection", "--save",
                "--title=Save recording as", f"--filename={folder / name}",
            )
            if code != 0 or not chosen:
                return
            chosen_path = Path(chosen)
            folder_input.value = self.tilde(chosen_path.parent)
            # Keeping the suggested timestamp name means "use the default": leave Name empty
            name_input.value = "" if chosen_path.name == default else chosen_path.name
            self.log_line(f"Will save to [cyan]{chosen_path}[/]")
            return

        def picked(path: Path | None) -> None:
            if path:
                folder_input.value = self.tilde(path)
                self.log_line(f"Will save to [cyan]{path}[/]")

        self.push_screen(FolderPicker(folder), picked)

    async def action_full(self) -> None:
        if self.proc:
            return
        output = await focused_output()
        await self.start(["-o", output] if output else [])

    async def action_region(self) -> None:
        if self.proc:
            return
        if not shutil.which("slurp"):
            self.log_line("[red]slurp not found — needed to select a section[/]")
            return
        self.log_line("Select a region with the mouse (Esc to cancel)…")
        code, geometry = await run("slurp")
        if code != 0 or not geometry:
            self.log_line("[yellow]Selection cancelled[/]")
            return
        await self.start(["-g", geometry])

    async def start(self, extra_args: list[str]) -> None:
        target = self.target_file()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.log_line(f"[red]Can't use folder {target.parent}: {e.strerror}[/]")
            return
        self.current_file = target
        cmd = ["wf-recorder", "-y", *extra_args, "-f", str(self.current_file)]
        if self.query_one("#audio", Switch).value:
            cmd.append("--audio")

        self.log_line(f"[bold cyan]$ {' '.join(cmd)}[/]")
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,  # keep it from reading the TUI's keystrokes
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self.started_at = time.monotonic()
        self.set_recording(True)
        self.tick()
        self.run_worker(self.watch_process(self.proc), exclusive=True)

    async def watch_process(self, proc: asyncio.subprocess.Process) -> None:
        """Collect wf-recorder output and clean up when it exits (stopped or crashed)."""
        # ffmpeg/x264 are very chatty, so keep the tail and only show it on failure
        tail: list[str] = []
        async for raw in proc.stdout:
            # wf-recorder redraws its progress line with \r; only keep real messages
            line = raw.decode(errors="replace").split("\r")[-1].strip()
            if line:
                tail = [*tail[-9:], line]
        code = await proc.wait()
        self.proc = None
        self.set_recording(False)

        if self.current_file and self.current_file.exists():
            self.log_line(f"[green]Saved {self.current_file}[/]\n")
            self.notify(f"Saved {self.current_file.name}", title="Recording finished")
            if shutil.which("notify-send"):
                await run("notify-send", "Recording saved", str(self.current_file))
        else:
            for line in tail:
                self.log_line(f"[dim]{line}[/]")
            self.log_line(f"[red]wf-recorder exited with code {code}, nothing saved[/]\n")

    async def action_stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.log_line("Stopping…")
            self.proc.send_signal(signal.SIGINT)  # same as Ctrl+C: finalises the file

    async def action_quit(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.send_signal(signal.SIGINT)
            await self.proc.wait()
        self.exit()


if __name__ == "__main__":
    Recorder().run()
