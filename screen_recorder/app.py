"""The Screen Recorder app: a terminal UI around wf-recorder."""

import asyncio
import signal
import sys
import time
from enum import Enum
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label, RadioButton, RadioSet, RichLog, Static,
    TabbedContent, TabPane,
)
from textual.worker import Worker

from . import config, system
from .dialogs import ConfirmDelete, FolderPicker, RenameScreen
from .recordings import RecordingsPane
from .util import (
    LOGO_PIXELS, DirectorySuggester, default_name, pixel_art, rich_color, tilde, unique_path,
)


class State(Enum):
    IDLE = "idle"
    COUNTDOWN = "countdown"
    RECORDING = "recording"


class Recorder(App):
    TITLE = "Screen Recorder"
    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("f", "full", "Full screen"),
        ("s", "region", "Section"),
        ("x", "stop", "Stop"),
        ("a", "cycle_audio", "Audio"),
        ("t", "cycle_countdown", "Countdown"),
        ("b", "browse", "Browse"),
        # Recordings list: the keys are shown on its buttons, so keep the footer short
        Binding("p", "play", "Play", show=False),
        Binding("o", "open_folder", "Folder", show=False),
        Binding("c", "copy_path", "Copy path", show=False),
        Binding("n", "rename", "Rename", show=False),
        Binding("d", "delete", "Delete", show=False),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, use_zenity: bool = True) -> None:
        super().__init__()
        self.use_zenity = use_zenity
        self.settings = config.load_config()
        self.delay = config.countdown(self.settings)
        self.state = State.IDLE
        self.proc: asyncio.subprocess.Process | None = None  # wf-recorder, while recording
        self.countdown_worker: Worker | None = None  # so X can cancel it
        self.current_file: Path | None = None
        self.started_at = 0.0

    def compose(self) -> ComposeResult:
        # Widgets with the "lock" class are disabled during a countdown or recording
        yield Header(icon="◉")  # the icon opens the command palette (themes, …)
        with Vertical(id="main"):
            with Horizontal(id="top"):
                yield Static(id="logo")
                with Vertical(id="status-card", classes="card") as card:
                    card.border_title = "Status"
                    yield Static(id="status")
                    yield Static(id="status-hint")
            with Horizontal(id="buttons"):
                yield Button("▣  Full screen  [dim]F[/]", id="full", variant="primary", classes="lock")
                yield Button("▢  Section  [dim]S[/]", id="region", variant="primary", classes="lock")
                yield Button(id="cycle_countdown", classes="lock",
                             tooltip="Countdown before recording starts")
                yield Button("■  Stop  [dim]X[/]", id="stop", variant="error")
            with Grid(id="output", classes="card") as card:
                card.border_title = "Output"
                yield Label("Folder")
                yield Input(self.settings.get("folder", tilde(config.DEFAULT_FOLDER)),
                            id="dir", suggester=DirectorySuggester(), classes="lock")
                yield Button("Browse  [dim]B[/]", id="browse", classes="lock")
                yield Label("Name")
                yield Input(placeholder="recording-<date>-<time>  (default)", id="name", classes="lock")
                yield Label("Audio")
                source = config.audio_source(self.settings)
                with RadioSet(id="audio", classes="lock"):
                    for key, label in config.AUDIO_SOURCES.items():
                        yield RadioButton(label, value=key == source, id=f"audio-{key}")
            with TabbedContent(id="bottom"):
                with TabPane("Recordings", id="tab-recordings"):
                    yield RecordingsPane()
                with TabPane("Activity", id="tab-activity"):
                    yield RichLog(markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        if self.settings.get("theme") in self.available_themes:
            self.theme = self.settings["theme"]
        # Remember the theme picked from the command palette (Ctrl+P → "Change theme")
        self.watch(self, "theme", lambda theme: config.save_config(theme=theme), init=False)
        self.watch(self, "theme", lambda _: self.draw_logo())
        if not system.available("wf-recorder"):
            self.log_line("[red]wf-recorder not found in PATH[/]")
        self.log_line("[dim]Tip: Enter or Esc leaves a text field so the shortcuts work again.[/]")
        self.refresh_recordings()
        self.show_delay()
        self.set_state(State.IDLE)
        self.set_focus(None)  # nothing focused, so the single-key shortcuts work at once
        self.set_interval(1, self.tick)

    # ---- state and display ------------------------------------------------

    def check_action(self, action: str, parameters) -> bool | None:
        # Single-letter shortcuts must not fire behind a dialog (e.g. F in the folder browser)
        if isinstance(self.screen, ModalScreen) and action != "quit":
            return False
        return True

    def busy(self) -> bool:
        return self.state is not State.IDLE

    def set_state(self, state: State) -> None:
        self.state = state
        busy = self.busy()
        for widget in self.query(".lock"):
            widget.disabled = busy
        self.query_one("#stop", Button).disabled = not busy
        card = self.query_one("#status-card")
        card.set_class(state is State.COUNTDOWN, "counting")
        card.set_class(state is State.RECORDING, "recording")
        if state is State.IDLE:
            self.show_status("○  READY", "Press F for full screen or S to record a section")

    def draw_logo(self) -> None:
        # Pixel art needs real colours, so take them from the current theme
        colors = self.get_css_variables()
        # A blank pixel row above and below shifts the 3-line logo down half a line, so it
        # spans the 4-line Status card from its top border line to its bottom one
        blank = "." * len(LOGO_PIXELS[0])
        self.query_one("#logo", Static).update(
            pixel_art([blank, *LOGO_PIXELS, blank], {
                "B": rich_color(colors["foreground"], "default"),
                "R": rich_color(colors["error"], "red"),
            })
        )

    def show_status(self, title: str, hint: str) -> None:
        self.query_one("#status", Static).update(title)
        self.query_one("#status-hint", Static).update(hint)

    def tick(self) -> None:
        if self.state is State.RECORDING:
            elapsed = int(time.monotonic() - self.started_at)
            dot = "●" if elapsed % 2 == 0 else "○"  # blink
            self.show_status(f"{dot}  REC  {elapsed // 60:02d}:{elapsed % 60:02d}",
                             f"→ {tilde(self.current_file)}")

    def show_delay(self) -> None:
        text = f"{self.delay} s" if self.delay else "Off"
        self.query_one("#cycle_countdown", Button).label = f"◔ {text}  [dim]T[/]"

    def log_line(self, text: str) -> None:
        self.query_one(RichLog).write(text)

    def show_tab(self, tab: str) -> None:
        self.query_one("#bottom", TabbedContent).active = f"tab-{tab}"

    # ---- settings ---------------------------------------------------------

    def countdown_seconds(self) -> int:
        return self.delay

    def audio_source(self) -> str:
        pressed = self.query_one("#audio", RadioSet).pressed_button
        return pressed.id.removeprefix("audio-") if pressed else "off"

    def save_folder(self) -> Path:
        return Path(self.query_one("#dir", Input).value.strip() or config.DEFAULT_FOLDER).expanduser()

    def target_file(self) -> Path:
        name = self.query_one("#name", Input).value.strip() or default_name()
        if not Path(name).suffix:
            name += ".mp4"
        return unique_path(self.save_folder() / name)

    def on_input_changed(self, event: Input.Changed) -> None:
        # Only remember real folders, not half-typed paths
        if event.input.id == "dir" and Path(event.value.strip()).expanduser().is_dir():
            config.save_config(folder=event.value.strip())

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "audio":
            config.save_config(audio_source=self.audio_source())

    def on_input_submitted(self) -> None:
        self.set_focus(None)  # give the keys back to the F/S/X shortcuts

    def on_key(self, event) -> None:
        if event.key == "escape" and isinstance(self.focused, Input):
            self.set_focus(None)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        await self.run_action(event.button.id)  # button ids are action names

    def action_cycle_audio(self) -> None:
        if self.busy():
            return
        buttons = list(self.query_one("#audio", RadioSet).query(RadioButton))
        current = next((i for i, b in enumerate(buttons) if b.value), -1)
        buttons[(current + 1) % len(buttons)].value = True

    def action_cycle_countdown(self) -> None:
        if self.busy():
            return
        self.delay = config.COUNTDOWNS[(config.COUNTDOWNS.index(self.delay) + 1) % len(config.COUNTDOWNS)]
        config.save_config(countdown=self.delay)
        self.show_delay()

    async def action_browse(self) -> None:
        if self.busy():
            return
        folder_input = self.query_one("#dir", Input)
        name_input = self.query_one("#name", Input)
        folder = self.save_folder()
        if not folder.is_dir():
            folder = Path.home()

        if self.use_zenity and system.available("zenity"):
            # Native "Save as" dialog: pick the folder and the file name in one go
            default = default_name()
            chosen = await system.ask_save_path(folder / (name_input.value.strip() or default))
            if chosen is None:
                return
            folder_input.value = tilde(chosen.parent)
            # Keeping the suggested timestamp name means "use the default": leave Name empty
            name_input.value = "" if chosen.name == default else chosen.name
            self.log_line(f"Will save to [cyan]{chosen}[/]")
            return

        def picked(path: Path | None) -> None:
            if path:
                folder_input.value = tilde(path)
                self.log_line(f"Will save to [cyan]{path}[/]")

        self.push_screen(FolderPicker(folder), picked)

    # ---- recording --------------------------------------------------------

    async def action_full(self) -> None:
        if self.busy():
            return
        output = await system.focused_output()
        await self.begin(["-o", output] if output else [])

    async def action_region(self) -> None:
        if self.busy():
            return
        if not system.available("slurp"):
            self.log_line("[red]slurp not found — needed to select a section[/]")
            return
        self.log_line("Select a region with the mouse (Esc to cancel)…")
        geometry = await system.select_region()
        if geometry is None:
            self.log_line("[yellow]Selection cancelled[/]")
            return
        await self.begin(["-g", geometry])

    async def begin(self, area_args: list[str]) -> None:
        """Start recording, after the countdown if one is set."""
        if not self.delay:
            await self.start(area_args)
            return
        # Set the state before creating the worker: Textual runs tasks eagerly, so the
        # worker's first steps may run before run_worker() even returns
        self.set_state(State.COUNTDOWN)
        # A worker, so the app keeps handling keys (X cancels) while it counts down
        self.countdown_worker = self.run_worker(self.count_down(self.delay, area_args),
                                                group="countdown")

    async def count_down(self, seconds: int, area_args: list[str]) -> None:
        system.notify("Screen Recorder", f"Recording starts in {seconds} s", timeout_ms=seconds * 1000)
        try:
            for left in range(seconds, 0, -1):
                self.show_status(f"◔  STARTING IN {left}…", "Press X to cancel")
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            self.log_line("[yellow]Countdown cancelled[/]")
            raise
        finally:
            self.set_state(State.IDLE)
        await self.start(area_args)

    async def start(self, area_args: list[str]) -> None:
        target = self.target_file()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.log_line(f"[red]Can't use folder {target.parent}: {e.strerror}[/]")
            return
        cmd = ["wf-recorder", "-y", *area_args, "-f", str(target)]
        source = self.audio_source()
        if source == "mic":
            cmd.append("--audio")  # default input device
        elif source == "system":
            device = await system.system_audio_device()
            if not device:
                self.log_line("[red]Can't find the system audio device (is pactl installed?)[/]")
                return
            cmd.append(f"--audio={device}")

        self.current_file = target
        self.log_line(f"[bold cyan]$ {' '.join(cmd)}[/]")
        self.proc = await system.start_wf_recorder(cmd)
        self.started_at = time.monotonic()
        self.set_state(State.RECORDING)
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
        self.set_state(State.IDLE)

        saved = self.current_file
        if saved and saved.exists():
            self.log_line(f"[green]Saved {saved}[/]\n")
            config.remember_recording(saved)
            self.refresh_recordings(select=saved)
            self.show_tab("recordings")
            self.notify(f"Saved {saved.name}", title="Recording finished")
            system.notify("Recording saved", str(saved))
        else:
            for line in tail:
                self.log_line(f"[dim]{line}[/]")
            self.log_line(f"[red]wf-recorder exited with code {code}, nothing saved[/]\n")
            self.show_tab("activity")

    async def action_stop(self) -> None:
        if self.state is State.COUNTDOWN and self.countdown_worker is not None:
            self.countdown_worker.cancel()
        elif self.proc and self.proc.returncode is None:
            self.log_line("Stopping…")
            self.proc.send_signal(signal.SIGINT)  # same as Ctrl+C: finalises the file

    async def action_quit(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.send_signal(signal.SIGINT)
            await self.proc.wait()
        self.exit()

    # ---- recordings list --------------------------------------------------

    def refresh_recordings(self, select: Path | None = None) -> None:
        self.query_one(RecordingsPane).show(config.recent_recordings(), select)

    def selected_recording(self) -> Path | None:
        path = self.query_one(RecordingsPane).selected()
        if path is None:
            self.notify("No recordings yet", severity="warning")
            return None
        if not path.exists():
            self.notify(f"{path.name} no longer exists", severity="warning")
            self.refresh_recordings()
            return None
        return path

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_play()  # Enter on a row

    def action_play(self) -> None:
        if (path := self.selected_recording()) and not system.open_with_default_app(path):
            self.notify("xdg-open not found (install xdg-utils)", severity="error")

    async def action_open_folder(self) -> None:
        if (path := self.selected_recording()) and not await system.show_in_file_manager(path):
            self.notify("xdg-open not found (install xdg-utils)", severity="error")

    async def action_copy_path(self) -> None:
        if not (path := self.selected_recording()):
            return
        if not await system.copy_to_clipboard(str(path)):
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
            history = config.recent_recordings()
            try:
                path.rename(target)
            except OSError as e:
                self.notify(f"Couldn't rename: {e.strerror}", severity="error")
                return
            config.rename_recording(path, target, history)
            self.log_line(f"Renamed {path.name} → [cyan]{target.name}[/]")
            self.refresh_recordings(select=target)

        self.push_screen(RenameScreen(path), done)

    def action_delete(self) -> None:
        if not (path := self.selected_recording()):
            return
        to_trash = system.can_trash()

        async def done(confirmed: bool) -> None:
            if not confirmed:
                return
            if not await system.delete(path):
                self.notify(f"Couldn't delete {path.name}", severity="error")
                return
            config.forget_recording(path)
            self.log_line(f"{'Moved to Trash' if to_trash else 'Deleted'}: {path.name}")
            self.refresh_recordings()

        self.push_screen(ConfirmDelete(path, to_trash), done)


def main() -> None:
    # --no-zenity: always use the in-terminal folder browser (handy for testing it)
    Recorder(use_zenity="--no-zenity" not in sys.argv[1:]).run()
