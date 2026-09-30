"""Choosing where recordings go and what they're called."""

import asyncio

from textual.widgets import Input

from conftest import SIZE, record, recording, run
from screen_recorder import config
from screen_recorder.dialogs import FolderPicker


def test_custom_folder_and_name(env):
    async def test():
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            app.query_one("#dir", Input).value = str(env.videos / "new" / "sub")
            await pilot.click("#name")
            await pilot.press(*"demo fsx")  # letters go into the field, not to the shortcuts
            await pilot.press("enter")
            assert not recording(app)

            first = await record(app, pilot)
            second = await record(app, pilot)
            assert first == env.videos / "new" / "sub" / "demo fsx.mp4"
            assert second.name == "demo fsx-1.mp4"  # never overwritten
    run(test)


def test_extension_in_name_is_kept(env):
    async def test():
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            app.query_one("#name", Input).value = "clip.mkv"
            assert (await record(app, pilot)).name == "clip.mkv"
    run(test)


def test_only_existing_folders_are_remembered(env):
    async def test():
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            app.query_one("#dir", Input).value = str(env.videos / "half-typ")
            await pilot.pause()
            assert config.load_config()["folder"] == str(env.videos)
            (env.videos / "real").mkdir()
            app.query_one("#dir", Input).value = str(env.videos / "real")
            await pilot.pause()
            assert config.load_config()["folder"] == str(env.videos / "real")
    run(test)


def test_browse_with_zenity_fills_folder_and_name(env, monkeypatch):
    async def test():
        monkeypatch.setenv("FAKE_ZENITY_PICK", str(env.videos / "picked" / "clip.mkv"))
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("b")
            await asyncio.sleep(0.3)
            assert app.query_one("#dir", Input).value.endswith("videos/picked")
            assert app.query_one("#name", Input).value == "clip.mkv"
    run(test)


def test_browse_keeps_name_empty_when_the_default_is_accepted(env, monkeypatch):
    async def test():
        # A zenity that just returns the suggested path, i.e. the user pressed Save
        (env.root / "bin" / "zenity").write_text(
            '#!/bin/sh\nfor a; do case $a in --filename=*) echo "${a#--filename=}";; esac; done\n')
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("b")
            await asyncio.sleep(0.3)
            assert app.query_one("#name", Input).value == ""
    run(test)


def test_browse_without_zenity_opens_the_folder_browser(env):
    async def test():
        app = env.app(use_zenity=False)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("b")
            await pilot.pause()
            assert isinstance(app.screen, FolderPicker)
            await pilot.press("f")  # shortcuts are off while a dialog is open
            await asyncio.sleep(0.3)
            assert not recording(app)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, FolderPicker)
    run(test)


def test_zenity_missing_falls_back_to_folder_browser(env):
    async def test():
        env.hide("zenity")
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("b")
            await pilot.pause()
            assert isinstance(app.screen, FolderPicker)
    run(test)
