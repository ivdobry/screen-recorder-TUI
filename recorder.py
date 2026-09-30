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
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets import (
    Button, DataTable, DirectoryTree, Footer, Header, Input, Label, RadioButton, RadioSet,
    RichLog, Static, TabbedContent, TabPane,
)

OUTPUT_DIR = Path.home() / "Videos"
# --no-zenity: always use the in-terminal folder browser (handy for testing it)
USE_ZENITY = "--no-zenity" not in sys.argv
CONFIG_FILE = Path.home() / ".config" / "screen-recorder-tui" / "config.json"
AUDIO_SOURCES = {"off": "Off", "mic": "Microphone", "system": "System sound"}
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


def recent_recordings() -> list[Path]:
    """Recordings made with the app, newest first, skipping files that are gone."""
    paths = [Path(p) for p in load_config().get("recent", [])]
    existing = [p for p in paths if p.exists()]
    if len(existing) != len(paths):
        save_config(recent=[str(p) for p in existing])
    return existing


def set_recent(paths: list[Path]) -> None:
    save_config(recent=[str(p) for p in paths[:MAX_RECENT]])


def human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


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


async def video_length(path: Path) -> str:
    if not shutil.which("ffprobe"):
        return "—"
    code, out = await run(
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)
    )
    try:
        seconds = round(float(out))
    except ValueError:
        return "—"
    return f"{seconds // 60}:{seconds % 60:02d}"


async def system_audio_device() -> str | None:
    """Monitor source of the current default output, i.e. "what you hear"."""
    if not shutil.which("pactl"):
        return None
    code, sink = await run("pactl", "get-default-sink")
    return f"{sink}.monitor" if code == 0 and sink else None


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


class RenameScreen(ModalScreen[str | None]):
    CSS = """
    RenameScreen { align: center middle; }
    #dialog { width: 60; height: auto; border: round $accent; background: $surface; padding: 1 2; }
    #dialog Input { margin: 1 0; }
    #dialog Horizontal { height: auto; align-horizontal: right; }
    #dialog Button { margin-left: 1; }
    """
    BINDINGS = [("escape", "dismiss(None)", "Cancel")]

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"Rename [b]{self.path.name}[/]")
            yield Input(self.path.stem, id="new-name")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Rename", id="ok", variant="primary")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        value = self.query_one("#new-name", Input).value.strip()
        self.dismiss(value or None if event.button.id == "ok" else None)


class ConfirmDelete(ModalScreen[bool]):
    CSS = """
    ConfirmDelete { align: center middle; }
    #dialog { width: 60; height: auto; border: round $error; background: $surface; padding: 1 2; }
    #dialog Horizontal { height: auto; align-horizontal: right; margin-top: 1; }
    #dialog Button { margin-left: 1; }
    """
    BINDINGS = [("escape,n", "dismiss(False)", "Cancel"), ("y", "dismiss(True)", "Delete")]

    def __init__(self, path: Path, to_trash: bool) -> None:
        super().__init__()
        self.path, self.to_trash = path, to_trash

    def compose(self) -> ComposeResult:
        what = "Move to Trash" if self.to_trash else "Permanently delete"
        with Vertical(id="dialog"):
            yield Label(f"{what} [b]{self.path.name}[/]?")
            with Horizontal():
                yield Button("Cancel  [dim]N[/]", id="cancel")
                yield Button("Delete  [dim]Y[/]", id="ok", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "ok")


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
    #name, #audio { column-span: 2; }
    #audio { layout: horizontal; width: 100%; height: 3; }
    #audio RadioButton { width: auto; margin-right: 4; }

    #bottom { height: 1fr; min-height: 10; }
    #bottom TabPane { padding: 0; }
    #bottom RichLog, #recent {
        height: 1fr;
        background: transparent;
        scrollbar-size-vertical: 1;
        scrollbar-background: $surface;
        scrollbar-color: $primary 40%;
    }
    #empty { color: $text-muted; padding: 1 1; }
    #rec-actions { height: auto; }
    #rec-actions Button { width: 1fr; min-width: 10; margin: 0 1 0 0; }
    #rec-actions Button:last-of-type { margin-right: 0; }
    #delete { color: $error; }
    """
    BINDINGS = [
        ("f", "full", "Full screen"),
        ("s", "region", "Section"),
        ("x", "stop", "Stop"),
        ("a", "cycle_audio", "Audio"),
        ("b", "browse", "Browse"),
        # Recordings list: the keys are shown on its buttons, so keep the footer short
        Binding("p", "play", "Play", show=False),
        Binding("o", "open_folder", "Folder", show=False),
        Binding("c", "copy_path", "Copy path", show=False),
        Binding("n", "rename", "Rename", show=False),
        Binding("d", "delete", "Delete", show=False),
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
                # Older configs stored a plain on/off "audio" flag, which meant the mic
                source = config.get("audio_source") or ("mic" if config.get("audio") else "off")
                with RadioSet(id="audio"):
                    for key, label in AUDIO_SOURCES.items():
                        yield RadioButton(label, value=key == source, id=f"audio-{key}")
            with TabbedContent(id="bottom"):
                with TabPane("Recordings", id="tab-recordings"):
                    yield Static("No recordings yet. Press F or S to make one.", id="empty")
                    yield DataTable(id="recent", cursor_type="row", zebra_stripes=True)
                    with Horizontal(id="rec-actions"):
                        yield Button("▶ Play  [dim]P[/]", id="play")
                        yield Button("Folder  [dim]O[/]", id="open_folder")
                        yield Button("Copy path  [dim]C[/]", id="copy_path")
                        yield Button("Rename  [dim]N[/]", id="rename")
                        yield Button("Delete  [dim]D[/]", id="delete")
                with TabPane("Activity", id="tab-activity"):
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
        table = self.query_one("#recent", DataTable)
        self.columns = dict(zip(
            ("name", "folder", "length", "size", "date"),
            table.add_columns("Name", "Folder", "Length", "Size", "Recorded"),
        ))
        self.refresh_recordings()
        self.set_recording(False)
        self.set_focus(None)  # nothing focused, so the single-key shortcuts work at once
        self.set_interval(1, self.tick)

    # ---- UI helpers -------------------------------------------------------

    def check_action(self, action: str, parameters) -> bool | None:
        # Single-letter shortcuts must not fire behind a dialog (e.g. F in the folder browser)
        if isinstance(self.screen, ModalScreen) and action != "quit":
            return False
        return True

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

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "audio":
            save_config(audio_source=self.audio_source())

    def audio_source(self) -> str:
        pressed = self.query_one("#audio", RadioSet).pressed_button
        return pressed.id.removeprefix("audio-") if pressed else "off"

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
        self.query_one("#audio", RadioSet).disabled = recording
        self.query_one("#dir", Input).disabled = recording
        self.query_one("#name", Input).disabled = recording
        self.query_one("#browse", Button).disabled = recording
        self.query_one("#status-card").set_class(recording, "recording")
        if not recording:
            self.query_one("#status", Static).update("○  READY")
            self.query_one("#status-hint", Static).update(
                "Press F for full screen or S to record a section"
            )

    # ---- recordings list ---------------------------------------------------

    def refresh_recordings(self, select: Path | None = None) -> None:
        table = self.query_one("#recent", DataTable)
        table.clear()
        paths = recent_recordings()
        for path in paths:
            stat = path.stat()
            table.add_row(
                path.name,
                self.tilde(path.parent),
                "…",
                human_size(stat.st_size),
                f"{datetime.fromtimestamp(stat.st_mtime):%d %b %H:%M}",
                key=str(path),
            )
        empty = not paths
        self.query_one("#empty").display = empty
        table.display = not empty
        for button in self.query("#rec-actions Button"):
            button.disabled = empty
        if select and str(select) in table.rows:
            table.move_cursor(row=table.get_row_index(str(select)))
        self.run_worker(self.fill_lengths(paths), group="lengths", exclusive=True)

    async def fill_lengths(self, paths: list[Path]) -> None:
        table = self.query_one("#recent", DataTable)
        for path in paths:
            length = await video_length(path)
            if str(path) in table.rows:
                table.update_cell(str(path), self.columns["length"], length)

    def selected_recording(self) -> Path | None:
        table = self.query_one("#recent", DataTable)
        if not table.row_count:
            self.notify("No recordings yet", severity="warning")
            return None
        path = Path(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)
        if not path.exists():
            self.notify(f"{path.name} no longer exists", severity="warning")
            self.refresh_recordings()
            return None
        return path

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_play()  # Enter on a row

    def open_with_default_app(self, path: Path) -> None:
        if shutil.which("xdg-open"):
            spawn("xdg-open", str(path))
        else:
            self.notify("xdg-open not found (install xdg-utils)", severity="error")

    def action_play(self) -> None:
        if path := self.selected_recording():
            self.open_with_default_app(path)

    async def action_open_folder(self) -> None:
        if not (path := self.selected_recording()):
            return
        # Ask the file manager to open the folder with the file selected; fall back to the folder
        code, _ = await run(
            "gdbus", "call", "--session",
            "--dest", "org.freedesktop.FileManager1",
            "--object-path", "/org/freedesktop/FileManager1",
            "--method", "org.freedesktop.FileManager1.ShowItems",
            f"['{path.as_uri()}']", "",
        ) if shutil.which("gdbus") else (1, "")
        if code != 0:
            self.open_with_default_app(path.parent)

    async def action_copy_path(self) -> None:
        if not (path := self.selected_recording()):
            return
        if shutil.which("wl-copy"):
            await run("wl-copy", "--", str(path))
        else:
            self.copy_to_clipboard(str(path))  # via the terminal (OSC 52)
        self.notify(str(path), title="Path copied")

    def action_rename(self) -> None:
        if not (path := self.selected_recording()):
            return

        def done(new_name: str | None) -> None:
            if not new_name or new_name == path.stem:
                return
            if "/" in new_name:
                self.notify("The name can't contain /", severity="error")
                return
            target = path.with_name(new_name if Path(new_name).suffix else new_name + path.suffix)
            if target.exists():
                self.notify(f"{target.name} already exists", severity="error")
                return
            history = recent_recordings()
            try:
                path.rename(target)
            except OSError as e:
                self.notify(f"Couldn't rename: {e.strerror}", severity="error")
                return
            set_recent([target if p == path else p for p in history])  # keep its place
            self.log_line(f"Renamed {path.name} → [cyan]{target.name}[/]")
            self.refresh_recordings(select=target)

        self.push_screen(RenameScreen(path), done)

    def action_delete(self) -> None:
        if not (path := self.selected_recording()):
            return
        to_trash = bool(shutil.which("gio"))

        async def done(confirmed: bool) -> None:
            if not confirmed:
                return
            if to_trash:
                code, _ = await run("gio", "trash", str(path))
                ok = code == 0
            else:
                try:
                    path.unlink()
                    ok = True
                except OSError:
                    ok = False
            if not ok:
                self.notify(f"Couldn't delete {path.name}", severity="error")
                return
            set_recent([p for p in recent_recordings() if p != path])
            self.log_line(f"{'Moved to Trash' if to_trash else 'Deleted'}: {path.name}")
            self.refresh_recordings()

        self.push_screen(ConfirmDelete(path, to_trash), done)

    def tick(self) -> None:
        if self.proc:
            elapsed = int(time.monotonic() - self.started_at)
            dot = "●" if elapsed % 2 == 0 else "○"  # blink
            self.query_one("#status", Static).update(f"{dot}  REC  {elapsed // 60:02d}:{elapsed % 60:02d}")
            self.query_one("#status-hint", Static).update(f"→ {self.tilde(self.current_file)}")

    # ---- actions ----------------------------------------------------------

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        await self.run_action(event.button.id)

    def action_cycle_audio(self) -> None:
        radio_set = self.query_one("#audio", RadioSet)
        if radio_set.disabled:
            return
        buttons = list(radio_set.query(RadioButton))
        current = next((i for i, b in enumerate(buttons) if b.value), -1)
        buttons[(current + 1) % len(buttons)].value = True

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
        cmd = ["wf-recorder", "-y", *extra_args, "-f", str(target)]
        source = self.audio_source()
        if source == "mic":
            cmd.append("--audio")  # default input device
        elif source == "system":
            device = await system_audio_device()
            if not device:
                self.log_line("[red]Can't find the system audio device (is pactl installed?)[/]")
                return
            cmd.append(f"--audio={device}")
        self.current_file = target

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
            set_recent([self.current_file, *(p for p in recent_recordings() if p != self.current_file)])
            self.refresh_recordings(select=self.current_file)
            self.query_one("#bottom", TabbedContent).active = "tab-recordings"
            self.notify(f"Saved {self.current_file.name}", title="Recording finished")
            if shutil.which("notify-send"):
                await run("notify-send", "Recording saved", str(self.current_file))
        else:
            for line in tail:
                self.log_line(f"[dim]{line}[/]")
            self.log_line(f"[red]wf-recorder exited with code {code}, nothing saved[/]\n")
            self.query_one("#bottom", TabbedContent).active = "tab-activity"

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
