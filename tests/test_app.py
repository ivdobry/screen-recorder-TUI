"""Start-up and settings that apply to the whole app."""

from rich.color import Color
from rich.style import Style

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


def test_logo_follows_the_theme(env):
    async def test():
        app = env.app(theme="atom-one-dark")
        async with app.run_test(size=SIZE) as pilot:
            def colours():
                return {Style.parse(str(s.style)).color.triplet for s in app.query_one("#logo").render().spans}
            dark = colours()
            app.theme = "atom-one-light"
            await pilot.pause()
            light = colours()
            assert dark != light
            assert Color.parse(app.get_css_variables()["error"]).triplet in light
    run(test)


def test_starts_with_every_theme(env):
    """Regression: the ANSI themes crashed on start-up when drawing the logo."""
    async def test():
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            themes = sorted(app.available_themes)
        for theme in themes:
            app = env.app(theme=theme)
            async with app.run_test(size=SIZE) as pilot:
                await pilot.pause()
                assert app.theme == theme
                assert "▀" in app.query_one("#logo").render().plain or "▄" in app.query_one("#logo").render().plain
    run(test)


def test_header_bar_is_shown(env):
    async def test():
        app = env.app()
        async with app.run_test(size=SIZE) as pilot:
            header = app.query_one("Header")
            assert header.display and header.region.y == 0  # at the very top
            assert app.query_one("#logo").region.y > 0  # the logo row is below it
    run(test)
