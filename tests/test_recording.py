"""Starting, stopping and counting down."""

import asyncio
import time

import pytest

from conftest import SIZE, listed, record, recording, run, status, wait_for


def test_full_screen_records_the_focused_monitor(env):
    async def test():
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            saved = await record(app, pilot, "f")
            assert env.wf_calls() == [f"wf-recorder -y -o FAKE-1 -f videos/{saved.name}"]
            assert saved.exists()
            assert "READY" in status(app)
    run(test)


def test_section_records_the_selected_area(env):
    async def test():
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            await record(app, pilot, "s")
            assert "-g 10,20 300x200" in env.wf_calls()[0]
    run(test)


def test_stop_button_works_with_and_without_countdown(env):
    """Regression: with the countdown off, Stop used to do nothing (eager tasks race)."""
    async def test():
        for delay in (0, 3):
            app = env.app(countdown=delay)
            async with app.run_test(size=SIZE) as pilot:
                await pilot.click("#full")
                assert await wait_for(lambda: recording(app))
                await asyncio.sleep(0.3)
                await pilot.click("#stop")
                assert await wait_for(lambda: not recording(app)), f"didn't stop (countdown={delay})"
    run(test)


def test_saved_recording_is_listed_selected_and_announced(env):
    async def test():
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            first = await record(app, pilot)
            second = await record(app, pilot)
            assert listed(app) == [second.name, first.name]
            assert app.query_one("#recent").cursor_row == 0
            assert app.query_one("#bottom").active == "tab-recordings"
            assert any(c.startswith("notify-send Recording saved") for c in env.calls())
    run(test)


def test_failed_recording_shows_the_activity_log(env):
    async def test():
        # A wf-recorder that exits straight away without writing anything
        (env.root / "bin" / "wf-recorder").write_text("#!/bin/sh\necho 'failed to connect' >&2\nexit 1\n")
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("f")
            assert await wait_for(lambda: app.query_one("#bottom").active == "tab-activity")
            assert not recording(app)
            assert listed(app) == []
            assert "READY" in status(app)
    run(test)


def test_countdown_then_recording(env):
    async def test():
        app = env.app(countdown=3)
        async with app.run_test(size=SIZE) as pilot:
            card = app.query_one("#status-card")
            started = time.monotonic()
            await pilot.press("f")
            await asyncio.sleep(0.2)
            assert "STARTING IN 3" in status(app)
            assert card.has_class("counting") and not card.has_class("recording")
            assert app.query_one("#full").disabled and app.query_one("#dir").disabled
            assert not app.query_one("#stop").disabled

            await pilot.press("f", "t", "b")  # ignored while counting down
            assert await wait_for(lambda: recording(app))
            assert 2.7 < time.monotonic() - started < 4.0
            assert card.has_class("recording") and not card.has_class("counting")

            await pilot.press("x")
            await wait_for(lambda: not recording(app))
            calls = env.calls()
            assert sum(c.startswith("wf-recorder") for c in calls) == 1
            assert sum("Recording starts in 3 s" in c for c in calls) == 1
            assert not any(c.startswith("zenity") for c in calls)
            assert app.countdown_seconds() == 3
    run(test)


def test_x_cancels_the_countdown(env):
    async def test():
        app = env.app(countdown=3)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("f")
            await asyncio.sleep(1)
            await pilot.press("x")
            await asyncio.sleep(2.5)  # past the moment it would have started
            assert not recording(app)
            assert env.wf_calls() == []
            assert "READY" in status(app)
            assert not app.query_one("#full").disabled
    run(test)


def test_t_cycles_the_countdown(env):
    async def test():
        from screen_recorder import config
        app = env.app(countdown=3)
        async with app.run_test(size=SIZE) as pilot:
            seen = []
            for _ in range(4):
                await pilot.press("t")
                seen.append(app.countdown_seconds())
            assert seen == [5, 10, 0, 3]
            assert config.load_config()["countdown"] == 3
            assert "3 s" in str(app.query_one("#cycle_countdown").label)
    run(test)


@pytest.mark.parametrize("source, flag", [
    ("off", None),
    ("mic", "--audio"),
    ("system", "--audio=fake_sink.monitor"),
])
def test_audio_sources(env, source, flag):
    async def test():
        app = env.app(audio_source=source)
        async with app.run_test(size=SIZE) as pilot:
            await record(app, pilot)
            cmd = env.wf_calls()[0]
            if flag:
                assert cmd.endswith(flag)
            else:
                assert "--audio" not in cmd
    run(test)


def test_a_cycles_audio_source_and_saves_it(env):
    async def test():
        from screen_recorder import config
        app = env.app(audio_source="off")
        async with app.run_test(size=SIZE) as pilot:
            for expected in ("mic", "system", "off"):
                await pilot.press("a")
                assert config.load_config()["audio_source"] == expected
    run(test)


def test_system_sound_without_pactl_shows_an_error(env):
    async def test():
        env.hide("pactl")
        app = env.app(audio_source="system")
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("f")
            await asyncio.sleep(0.5)
            assert not recording(app)
            assert env.wf_calls() == []
    run(test)


def test_quit_stops_the_recording_first(env):
    async def test():
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("f")
            await wait_for(lambda: recording(app))
            proc = app.proc
            await pilot.press("q")
            await asyncio.sleep(0.5)
            assert proc.returncode is not None
    run(test)
