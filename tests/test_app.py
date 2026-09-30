"""Start-up and settings that apply to the whole app."""

from conftest import SIZE, run, status
from screen_recorder import config


def test_starts_ready(env):
    async def test():
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            assert "READY" in status(app)
            assert not app.query_one("#full").disabled
            assert app.query_one("#stop").disabled
            assert app.focused is None  # so single-key shortcuts work straight away
    run(test)


def test_restores_saved_settings(env):
    async def test():
        app = env.app(theme="nord", countdown=5, audio_source="system", folder="~/Somewhere")
        async with app.run_test(size=SIZE) as pilot:
            assert app.theme == "nord"
            assert app.countdown_seconds() == 5
            assert app.audio_source() == "system"
            assert app.query_one("#dir").value == "~/Somewhere"
    run(test)


def test_theme_change_is_saved(env):
    async def test():
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            app.theme = "atom-one-dark"
            await pilot.pause()
            assert config.load_config()["theme"] == "atom-one-dark"
    run(test)


def test_warns_when_wf_recorder_is_missing(env):
    async def test():
        env.hide("wf-recorder")
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            app.query_one("#bottom").active = "tab-activity"
            await pilot.pause()
            log = [line.text for line in app.query_one("RichLog").lines]
            assert any("wf-recorder not found" in line for line in log)
    run(test)
