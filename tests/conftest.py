"""Shared test setup.

App tests run the real app headless, with every external program replaced by a
small fake on PATH that logs how it was called. Nothing touches the real screen,
microphone, files or config.
"""

import asyncio
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from screen_recorder import config
from screen_recorder.app import Recorder

FAKES = {
    # Records until it gets SIGINT, then "saves" the sample video, like the real one
    "wf-recorder": """#!/bin/sh
echo "wf-recorder $*" >> "$FAKE_LOG"
for a; do [ "$prev" = "-f" ] && out=$a; prev=$a; done
trap 'cp "$FAKE_SAMPLE" "$out"; exit 0' INT
while :; do sleep 0.05; done
""",
    "slurp": '#!/bin/sh\necho "slurp $*" >> "$FAKE_LOG"\necho "10,20 300x200"\n',
    "niri": '#!/bin/sh\necho \'{"name": "FAKE-1"}\'\n',
    "pactl": '#!/bin/sh\necho "fake_sink"\n',
    "zenity": '#!/bin/sh\necho "zenity $*" >> "$FAKE_LOG"\necho "$FAKE_ZENITY_PICK"\n',
    "xdg-open": '#!/bin/sh\necho "xdg-open $*" >> "$FAKE_LOG"\n',
    "gdbus": '#!/bin/sh\necho "gdbus $*" >> "$FAKE_LOG"\n',
    "gio": '#!/bin/sh\necho "gio $*" >> "$FAKE_LOG"\n[ "$1" = trash ] && rm -f "$2"\n',
    "notify-send": '#!/bin/sh\necho "notify-send $*" >> "$FAKE_LOG"\n',
}

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class Env:
    """A throwaway home for one test: fake programs, a videos folder and a config file."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self.videos = root / "videos"
        self.videos.mkdir()
        self.log = root / "calls.log"
        self.sample = root / "sample.mp4"
        self.monkeypatch = monkeypatch

        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name, script in FAKES.items():
            (bin_dir / name).write_text(script)
            (bin_dir / name).chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
        monkeypatch.setenv("FAKE_LOG", str(self.log))
        monkeypatch.setenv("FAKE_SAMPLE", str(self.sample))
        monkeypatch.setattr(config, "CONFIG_FILE", root / "config" / "config.json")

        if HAS_FFMPEG:
            subprocess.run(
                ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=2:s=64x48",
                 "-pix_fmt", "yuv420p", str(self.sample)],
                check=True,
            )
        else:
            self.sample.write_bytes(b"not really a video")

    def hide(self, *programs: str) -> None:
        """Make programs unavailable, to test the fallbacks."""
        real = shutil.which
        self.monkeypatch.setattr(shutil, "which", lambda cmd, *a, **k: None if cmd in programs else real(cmd, *a, **k))

    def write_config(self, **settings) -> None:
        config.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.CONFIG_FILE.write_text(json.dumps({"folder": str(self.videos), "countdown": 0, **settings}))

    def app(self, use_zenity: bool = True, **settings) -> Recorder:
        self.write_config(**settings)
        return Recorder(use_zenity=use_zenity)

    def calls(self) -> list[str]:
        """Commands the fakes were called with since the last check (paths made relative)."""
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        self.log.unlink(missing_ok=True)
        return [line.replace(f"{self.root}/", "") for line in lines]

    def wf_calls(self) -> list[str]:
        return [c for c in self.calls() if c.startswith("wf-recorder")]

    def video(self, name: str) -> Path:
        path = self.videos / name
        shutil.copy(self.sample, path)
        return path


@pytest.fixture
def env(tmp_path, monkeypatch) -> Env:
    return Env(tmp_path, monkeypatch)


def run(test):
    """Run an async test body with eager tasks, like Textual does in App.run().

    (Textual's test mode doesn't enable them, which once hid a real bug.)
    """

    async def main():
        asyncio.get_running_loop().set_task_factory(asyncio.eager_task_factory)
        await test()

    asyncio.run(main())


async def wait_for(condition, timeout: float = 8.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        await asyncio.sleep(0.05)
    return False


def recording(app) -> bool:
    return app.proc is not None


async def record(app, pilot, key: str = "f", seconds: float = 0.5) -> Path:
    """Start with `key`, let it run a moment, stop with X and wait until it's saved."""
    await pilot.press(key)
    assert await wait_for(lambda: recording(app)), "recording never started"
    await asyncio.sleep(seconds)
    await pilot.press("x")
    assert await wait_for(lambda: not recording(app)), "recording never stopped"
    await asyncio.sleep(0.3)  # let the saved file reach the list
    return app.current_file


def listed(app) -> list[str]:
    table = app.query_one("#recent")
    return [str(table.get_row_at(i)[0]) for i in range(table.row_count)]


def status(app) -> str:
    return str(app.query_one("#status").render())


SIZE = (110, 44)
