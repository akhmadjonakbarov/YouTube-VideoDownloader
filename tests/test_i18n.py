import re
from datetime import datetime

import pytest

from config import i18n, user_settings


@pytest.fixture(autouse=True)
def reset_language():
    yield
    i18n.set_language("en")


def _base_keys(table):
    return {re.sub(r"\.(one|other)$", "", k) for k in table}


def test_every_key_is_translated():
    assert _base_keys(i18n.STRINGS["en"]) == _base_keys(i18n.STRINGS["uz"])


def test_placeholders_match():
    for key, english in i18n.STRINGS["en"].items():
        base = re.sub(r"\.(one|other)$", "", key)
        uzbek = i18n.STRINGS["uz"].get(key) or i18n.STRINGS["uz"].get(f"{base}.other")
        wanted = set(re.findall(r"{(\w+)}", english)) - {"n"}
        assert wanted <= set(re.findall(r"{(\w+)}", uzbek)), key


def test_t_and_fallbacks():
    i18n.set_language("uz")
    assert i18n.t("nav.library") == "Kutubxona"
    assert i18n.t("notify.fetch_error", message="x") == "Havolani o'qib bo'lmadi: x"
    assert i18n.t("no.such.key") == "no.such.key"
    i18n.set_language("fr")  # unsupported -> English
    assert i18n.get_language() == "en"


def test_plurals():
    assert i18n.tn("button.download_videos", 1) == "Download 1 video"
    assert i18n.tn("button.download_videos", 3) == "Download 3 videos"
    i18n.set_language("uz")
    assert i18n.tn("button.download_videos", 1) == "1 ta videoni yuklab olish"
    assert i18n.tn("activity.items", 3) == "3 ta yuklama"


def test_dates():
    ts = datetime(2025, 11, 13, 12, 0).timestamp()
    assert i18n.format_date(ts) == "13 Nov 2025"
    i18n.set_language("uz")
    assert i18n.format_date(ts) == "13 noy 2025"


@pytest.mark.parametrize("env, expected", [
    ({"LANG": "uz_UZ.UTF-8"}, "uz"),
    ({"LANG": "en_US.UTF-8"}, "en"),
    ({"LANGUAGE": "uz:en", "LANG": "en_US.UTF-8"}, "uz"),
    ({"LANG": "ru_RU.UTF-8"}, "en"),        # unsupported first choice -> English
    ({"LANG": "C.UTF-8"}, "en"),
    ({}, "en"),
])
def test_detect_from_environment(monkeypatch, env, expected):
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    monkeypatch.setattr(i18n.sys, "platform", "linux")
    monkeypatch.setattr(i18n.locale, "getlocale", lambda: (None, None))
    assert i18n.detect_system_language() == expected


def test_detect_on_macos(monkeypatch):
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(i18n.sys, "platform", "darwin")
    monkeypatch.setattr(i18n, "_macos_languages", lambda: ["uz-Latn-UZ", "en-US"])
    assert i18n.detect_system_language() == "uz"
    monkeypatch.setattr(i18n, "_macos_languages", lambda: ["en-US", "uz-UZ"])
    assert i18n.detect_system_language() == "en"


def test_macos_defaults_output_parsing(monkeypatch):
    class Result:
        stdout = '(\n    "uz-Latn-UZ",\n    "en-US"\n)\n'
    monkeypatch.setattr(i18n.subprocess, "run", lambda *a, **k: Result())
    assert i18n._macos_languages() == ["uz-Latn-UZ", "en-US"]


def test_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(user_settings, "settings_path", lambda: tmp_path / "x" / "settings.json")
    assert user_settings.load() == {}
    user_settings.save(language="uz")
    user_settings.save(theme="Light")
    assert user_settings.load() == {"language": "uz", "theme": "Light"}
    (tmp_path / "x" / "settings.json").write_text("not json")
    assert user_settings.load() == {}
