import asyncio
import re
from pathlib import Path

from screen_recorder.util import DirectorySuggester, default_name, human_size, tilde, unique_path


def test_tilde_shortens_home_paths():
    assert tilde(Path.home() / "Videos") == "~/Videos"
    assert tilde(Path("/tmp/x")) == "/tmp/x"


def test_default_name_is_a_timestamped_mp4():
    assert re.fullmatch(r"recording-\d{8}-\d{6}\.mp4", default_name())


def test_unique_path_never_overwrites(tmp_path):
    target = tmp_path / "demo.mp4"
    assert unique_path(target) == target
    target.touch()
    assert unique_path(target) == tmp_path / "demo-1.mp4"
    (tmp_path / "demo-1.mp4").touch()
    assert unique_path(target) == tmp_path / "demo-2.mp4"


def test_human_size():
    assert human_size(512) == "512 B"
    assert human_size(1536) == "1.5 KB"
    assert human_size(5 * 1024 ** 2) == "5.0 MB"
    assert human_size(3 * 1024 ** 4) == "3072.0 GB"


def test_directory_suggester(tmp_path):
    (tmp_path / "Videos").mkdir()
    (tmp_path / "Vault").mkdir()
    (tmp_path / "Video.txt").touch()  # files are never suggested
    (tmp_path / ".Vhidden").mkdir()  # neither are hidden folders
    suggest = DirectorySuggester().get_suggestion
    assert asyncio.run(suggest(f"{tmp_path}/Vid")) == f"{tmp_path}/Videos"
    assert asyncio.run(suggest(f"{tmp_path}/Va")) == f"{tmp_path}/Vault"
    assert asyncio.run(suggest(f"{tmp_path}/Videos")) is None  # already complete
    assert asyncio.run(suggest(f"{tmp_path}/nope")) is None


def test_logo_pixel_art():
    from screen_recorder.util import LOGO_PIXELS, pixel_art
    art = pixel_art(LOGO_PIXELS, {"B": "white", "R": "red"})
    assert art.plain.splitlines() == [
        "█▀  █▄▄█  ▀█",  # ears
        "   █▄██▄█   ",  # eyes
        "█▄  ▀▀▀▀  ▄█",  # chin
    ]
    assert {str(span.style) for span in art.spans} == {"white", "red"}


def test_pixel_art_two_colours_in_one_cell():
    from screen_recorder.util import pixel_art
    art = pixel_art(["A", "B"], {"A": "red", "B": "blue"})
    assert art.plain == "▀" and str(art.spans[0].style) == "red on blue"


def test_rich_color():
    from screen_recorder.util import rich_color
    assert rich_color("#ABB2BF", "red") == "#ABB2BF"
    assert rich_color("ansi_red", "x") == "red"  # the ANSI themes' colour names
    assert rich_color("ansi_default", "x") == "default"
    assert rich_color("ansi_bright_red", "x") == "bright_red"
    assert rich_color("auto 60%", "red") == "red"  # not a colour at all
