import json

import pytest

from screen_recorder import config


@pytest.fixture(autouse=True)
def temp_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "cfg" / "config.json")


def test_missing_or_broken_config_is_empty():
    assert config.load_config() == {}
    config.CONFIG_FILE.parent.mkdir(parents=True)
    config.CONFIG_FILE.write_text("{not json")
    assert config.load_config() == {}


def test_save_merges_with_existing_settings():
    config.save_config(theme="nord")
    config.save_config(countdown=5)
    assert json.loads(config.CONFIG_FILE.read_text()) == {"theme": "nord", "countdown": 5}


@pytest.mark.parametrize("settings, expected", [
    ({}, "off"),
    ({"audio": True}, "mic"),  # the old on/off setting meant the microphone
    ({"audio": False}, "off"),
    ({"audio_source": "system", "audio": True}, "system"),  # the new setting wins
    ({"audio_source": "bogus"}, "off"),
])
def test_audio_source(settings, expected):
    assert config.audio_source(settings) == expected


@pytest.mark.parametrize("settings, expected", [
    ({}, config.DEFAULT_COUNTDOWN),
    ({"countdown": 0}, 0),
    ({"countdown": 10}, 10),
    ({"countdown": 7}, config.DEFAULT_COUNTDOWN),  # not one of the choices
])
def test_countdown(settings, expected):
    assert config.countdown(settings) == expected


def test_recent_recordings(tmp_path):
    a, b, c = (tmp_path / f"{n}.mp4" for n in "abc")
    for p in (a, b, c):
        p.touch()

    config.remember_recording(a)
    config.remember_recording(b)
    assert config.recent_recordings() == [b, a]  # newest first

    config.remember_recording(a)
    assert config.recent_recordings() == [a, b]  # no duplicates, moved to the top

    history = config.recent_recordings()
    a.rename(c.with_name("renamed.mp4"))
    config.rename_recording(a, tmp_path / "renamed.mp4", history)
    assert config.recent_recordings() == [tmp_path / "renamed.mp4", b]  # keeps its place

    config.forget_recording(b)
    assert config.recent_recordings() == [tmp_path / "renamed.mp4"]


def test_recent_recordings_drops_missing_files(tmp_path):
    kept = tmp_path / "kept.mp4"
    kept.touch()
    config.save_config(recent=[str(kept), str(tmp_path / "gone.mp4")])
    assert config.recent_recordings() == [kept]
    assert config.load_config()["recent"] == [str(kept)]  # cleaned up on disk too


def test_recent_recordings_is_capped(tmp_path):
    for i in range(config.MAX_RECENT + 5):
        path = tmp_path / f"{i}.mp4"
        path.touch()
        config.remember_recording(path)
    recent = config.recent_recordings()
    assert len(recent) == config.MAX_RECENT
    assert recent[0].name == f"{config.MAX_RECENT + 4}.mp4"
