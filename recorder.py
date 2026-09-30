"""TUI front-end for wf-recorder: record full screen or a region, then stop."""

import asyncio
import json
import shutil
import signal
import time
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Header, RichLog, Static, Switch, Label

OUTPUT_DIR = Path.home() / "Videos"


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


class Recorder(App):
    TITLE = "Screen Recorder"
    CSS = """
    #status { padding: 1 2; text-style: bold; }
    #status.recording { background: $error; color: $text; }
    #buttons { height: auto; padding: 0 1; }
    #buttons Button { margin: 0 1; }
    #options { height: auto; padding: 1 2; }
    #options Label { padding: 1 1 0 0; }
    RichLog { border: round $secondary; margin: 0 1; }
    """
    BINDINGS = [
        ("f", "full", "Full screen"),
        ("s", "region", "Section"),
        ("x", "stop", "Stop"),
        ("a", "toggle_audio", "Audio"),
        ("q", "quit", "Quit"),
    ]

    proc: asyncio.subprocess.Process | None = None
    started_at = 0.0
    current_file: Path | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("● Idle", id="status")
        with Horizontal(id="buttons"):
            yield Button("Full screen [F]", id="full", variant="primary")
            yield Button("Section [S]", id="region", variant="primary")
            yield Button("Stop [X]", id="stop", variant="error", disabled=True)
        with Horizontal(id="options"):
            yield Label("Record audio")
            yield Switch(id="audio")
        yield RichLog(markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        if not shutil.which("wf-recorder"):
            self.log_line("[red]wf-recorder not found in PATH[/]")
        self.log_line(f"Recordings are saved to [cyan]{OUTPUT_DIR}[/]")
        self.set_interval(1, self.tick)

    # ---- UI helpers -------------------------------------------------------

    def log_line(self, text: str) -> None:
        self.query_one(RichLog).write(text)

    def set_recording(self, recording: bool) -> None:
        self.query_one("#full", Button).disabled = recording
        self.query_one("#region", Button).disabled = recording
        self.query_one("#stop", Button).disabled = not recording
        self.query_one("#audio", Switch).disabled = recording
        status = self.query_one("#status", Static)
        status.set_class(recording, "recording")
        if not recording:
            status.update("● Idle")

    def tick(self) -> None:
        if self.proc:
            elapsed = int(time.monotonic() - self.started_at)
            self.query_one("#status", Static).update(
                f"● REC  {elapsed // 60:02d}:{elapsed % 60:02d}  →  {self.current_file.name}"
            )

    # ---- actions ----------------------------------------------------------

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        await self.run_action(event.button.id)

    def action_toggle_audio(self) -> None:
        switch = self.query_one("#audio", Switch)
        if not switch.disabled:
            switch.toggle()

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
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.current_file = OUTPUT_DIR / f"recording-{datetime.now():%Y%m%d-%H%M%S}.mp4"
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
