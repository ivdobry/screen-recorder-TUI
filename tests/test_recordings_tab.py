"""The Recordings tab: listing, playing, opening, copying, renaming, deleting."""

import asyncio

import pytest
from textual.widgets import Input

from conftest import HAS_FFMPEG, SIZE, listed, recording, run
from screen_recorder import config
from screen_recorder.dialogs import ConfirmDelete, RenameScreen


def with_recordings(env, *names):
    paths = [env.video(n) for n in names]
    return env.app(recent=[str(p) for p in paths]), paths


def test_empty_list(env):
    async def test():
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            assert app.query_one("#empty").display
            assert all(b.disabled for b in app.query("#rec-actions Button"))
            await pilot.press("p")  # nothing selected: a warning, no crash
            assert env.calls() == []
    run(test)


def test_lists_recent_recordings_and_drops_missing_ones(env):
    async def test():
        keep = env.video("keep.mp4")
        app = env.app(recent=[str(keep), str(env.videos / "gone.mp4")])
        async with app.run_test(size=SIZE) as pilot:
            await asyncio.sleep(0.5)
            assert listed(app) == ["keep.mp4"]
    run(test)


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg/ffprobe")
def test_shows_video_length(env):
    async def test():
        app, _ = with_recordings(env, "a.mp4")
        async with app.run_test(size=SIZE) as pilot:
            await asyncio.sleep(0.8)
            assert str(app.query_one("#recent").get_row_at(0)[2]) == "0:02"
    run(test)


def test_play_open_folder_copy(env, monkeypatch):
    async def test():
        app, (path,) = with_recordings(env, "demo.mp4")
        copied = []
        monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("p")
            await asyncio.sleep(0.2)
            assert env.calls() == ["xdg-open videos/demo.mp4"]

            await pilot.press("o")
            await asyncio.sleep(0.2)
            assert any("FileManager1.ShowItems" in c and "demo.mp4" in c for c in env.calls())

            await pilot.press("c")  # no wl-copy in the fakes: uses the terminal clipboard
            assert copied == [str(path)]
    run(test)


def test_click_selects_without_playing(env):
    async def test():
        app, _ = with_recordings(env, "a.mp4", "b.mp4")
        async with app.run_test(size=SIZE) as pilot:
            await pilot.click("#recent", offset=(3, 2))
            await asyncio.sleep(0.2)
            assert env.calls() == []
    run(test)


def test_fallbacks_when_tools_are_missing(env, monkeypatch):
    async def test():
        env.hide("xdg-open", "gdbus", "gio")
        app, (path,) = with_recordings(env, "demo.mp4")
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("p", "o")
            await pilot.pause()
            messages = [n.message for n in app._notifications]
            assert messages.count("xdg-open not found (install xdg-utils)") == 2

            await pilot.press("d")  # without gio, delete is permanent and says so
            await pilot.pause()
            assert "Permanently delete" in str(app.screen.query_one("Label").render())
            await pilot.press("y")
            await asyncio.sleep(0.3)
            assert not path.exists()
    run(test)


def test_rename_keeps_extension_and_position(env):
    async def test():
        app, _ = with_recordings(env, "first.mp4", "second.mp4")
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("n")
            await pilot.pause()
            assert isinstance(app.screen, RenameScreen)
            await pilot.press("f")  # typed into the box, doesn't start a recording
            assert not recording(app)
            app.screen.query_one(Input).value = "renamed"
            await pilot.press("enter")
            await asyncio.sleep(0.3)
            assert listed(app) == ["renamed.mp4", "second.mp4"]
            assert (env.videos / "renamed.mp4").exists()
            assert config.recent_recordings()[0].name == "renamed.mp4"
    run(test)


def test_rename_refuses_existing_name(env):
    async def test():
        app, _ = with_recordings(env, "first.mp4", "second.mp4")
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("n")
            await pilot.pause()
            app.screen.query_one(Input).value = "second"
            await pilot.press("enter")
            await asyncio.sleep(0.3)
            assert listed(app) == ["first.mp4", "second.mp4"]
            assert (env.videos / "first.mp4").exists()
    run(test)


def test_delete_asks_first_then_trashes(env):
    async def test():
        app, (path,) = with_recordings(env, "demo.mp4")
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("d")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmDelete)
            await pilot.press("n")
            await pilot.pause()
            assert listed(app) == ["demo.mp4"] and path.exists()

            await pilot.press("d")
            await pilot.pause()
            await pilot.press("y")
            await asyncio.sleep(0.3)
            assert listed(app) == []
            assert env.calls() == ["gio trash videos/demo.mp4"]
            assert config.recent_recordings() == []
    run(test)


def test_file_removed_outside_the_app(env):
    async def test():
        app, (path,) = with_recordings(env, "demo.mp4")
        async with app.run_test(size=SIZE) as pilot:
            path.unlink()
            await pilot.press("p")
            await pilot.pause()
            assert env.calls() == []  # not played
            assert listed(app) == []  # and dropped from the list
    run(test)
