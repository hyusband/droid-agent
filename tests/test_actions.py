import pytest

from droid_agent.actions import Actions, parse_target
from droid_agent.adb import AdbError
from droid_agent.session import Session


def test_parse_target_ref():
    assert parse_target("7") == ("ref", (7, 0))
    assert parse_target("#12") == ("ref", (12, 0))


def test_parse_target_xy():
    assert parse_target("540,1050") == ("xy", (540, 1050))
    assert parse_target("540 1050") == ("xy", (540, 1050))


def test_parse_target_bad():
    with pytest.raises(AdbError):
        parse_target("hello")


class _FakeAdb:
    def __init__(self):
        self.calls = []

    def shell(self, cmd, timeout=None):
        self.calls.append(cmd)
        return ""


def test_tap_by_ref_uses_session():
    fake = _FakeAdb()
    s = Session(elements=[{"ref": 3, "center": [111, 222], "label": "OK"}])
    x, y = Actions(fake).tap("3", s)
    assert (x, y) == (111, 222)
    assert fake.calls == ["input tap 111 222"]


def test_tap_missing_ref():
    with pytest.raises(AdbError) as e:
        Actions(_FakeAdb()).tap("9", Session(elements=[]))
    assert "dump" in str(e.value)


def test_key_by_name_and_code():
    fake = _FakeAdb()
    assert Actions(fake).key("back") == 4
    assert Actions(fake).key("66") == 66
    with pytest.raises(AdbError):
        Actions(fake).key("nope")


def test_type_text_escapes():
    fake = _FakeAdb()
    Actions(fake).type_text('hola mundo & "co"')
    cmd = fake.calls[0]
    # spaces -> %s, double quotes escaped, & stays literal inside dq
    assert cmd == 'input text "hola%smundo%s&%s\\"co\\""'


def test_swipe_dir():
    fake = _FakeAdb()
    x1, y1, x2, y2 = Actions(fake).swipe_dir("up", (1080, 2400))
    assert x1 == x2 == 540
    assert y1 > y2  # swipe up = start lower, end higher
    with pytest.raises(AdbError):
        Actions(fake).swipe_dir("diagonal", (1080, 2400))
