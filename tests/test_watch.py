"""watch/events/unlock/read coverage — the live-view feature."""

import json
import socket
import threading
import time
import urllib.request

import pytest

from droid_agent import events
from droid_agent.actions import Actions
from droid_agent.device import DeviceOps
from droid_agent.ui import extract_text


@pytest.fixture
def events_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DROID_AGENT_HOME", str(tmp_path))
    return tmp_path


def _lines(home):
    p = home / "events.jsonl"
    return p.read_text(encoding="utf-8").splitlines() if p.exists() else []


def test_emit_appends_json(events_home):
    events.emit("tap", x=1, y=2, label="Allow")
    rec = json.loads(_lines(events_home)[0])
    assert rec["kind"] == "tap" and rec["x"] == 1 and rec["t"] > 0


def test_emit_never_raises(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")  # a file where a dir is needed → makedirs fails
    monkeypatch.setenv("DROID_AGENT_HOME", str(blocker / "sub"))
    events.emit("tap")  # unwritable path → swallow, never break the action


def test_tail_only_new(events_home):
    events.emit("old")
    gen = events.tail()
    next(gen)
    events.emit("new", n=1)
    got = None
    for _ in range(30):
        _, got = next(gen)
        if got:
            break
        time.sleep(0.02)
    assert got and json.loads(got)["kind"] == "new"


def test_recent_caps(events_home):
    for i in range(30):
        events.emit("k", i=i)
    assert len(events.recent(20)) == 20


def test_rotate(events_home, monkeypatch):
    monkeypatch.setattr(events, "_MAX_BYTES", 200)
    monkeypatch.setattr(events, "_KEEP_LINES", 5)
    for i in range(50):
        events.emit("k", i=i)
    assert len(_lines(events_home)) <= 5


class FakeAdb:
    """Adb duck-type for actions/device/watch — records shell calls."""

    def __init__(self, *a, **k):
        self.serial = "fake0"
        self.calls = []

    def _base(self):
        return ["true"]  # unix no-op — h264 producer exits instantly

    def require_device(self):
        pass

    def run(self, *a, **k):
        return ""

    def shell(self, cmd, timeout=None):
        self.calls.append(cmd)
        if "wm size" in cmd:
            return "Physical size: 1080x2400"
        if "getprop" in cmd:
            return "PixelFake"
        return ""

    def exec_out(self, cmd, timeout=None):
        return b"\x89PNG\r\n\x1a\nFAKEBYTES"


def test_tap_emits_xy_label(events_home, tmp_path, monkeypatch):
    monkeypatch.setenv("DROID_AGENT_HOME", str(tmp_path))
    adb = FakeAdb()
    Actions(adb).tap("540,1050")
    rec = json.loads(_lines(tmp_path)[0])
    assert rec["kind"] == "tap" and rec["x"] == 540 and "540" in rec["label"]


def test_type_never_logs_content(events_home):
    adb = FakeAdb()
    Actions(adb).type_text("s3cret-p4ss")
    rec = json.loads(_lines(events_home)[0])
    assert rec["kind"] == "type" and rec["chars"] == 11
    assert "s3cret" not in json.dumps(rec)


def test_unlock_command_order(events_home):
    adb = FakeAdb()
    DeviceOps(adb).unlock(pin="1234")
    calls = adb.calls
    assert calls[0] == "input keyevent 224"
    assert calls[1] == "wm size"
    assert calls[2].startswith("input swipe 540 2040 540 360")
    assert 'input text "1234"' in calls[3]
    assert calls[4] == "input keyevent 66"
    assert json.loads(_lines(events_home)[0])["kind"] == "unlock"


def test_escape_input_text():
    from droid_agent.actions import escape_input_text as esc
    assert esc("a b") == "a%sb"
    out = esc('say "hi" $5')
    assert '\\"' in out and "\\$" in out and "%s" in out
    assert esc("plain") == "plain"


_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="Hello world" resource-id="" class="android.widget.TextView"
        content-desc="" bounds="[0,100][1080,200]" clickable="false"/>
  <node index="1" text="secret\u200bfield" resource-id="" class="android.widget.EditText"
        content-desc="" bounds="[0,300][1080,400]" password="true" clickable="true"/>
  <node index="2" text="" resource-id="" class="android.widget.ImageView"
        content-desc="Profile photo" bounds="[0,500][200,700]" clickable="true"/>
</hierarchy>
"""


def test_extract_text_reads_all_visible():
    nodes = extract_text(_XML)
    texts = [n["text"] or n["desc"] for n in nodes]
    assert "Hello world" in texts           # non-actionable text is read
    assert "Profile photo" in texts          # content-desc too
    assert not any("secret" in t for t in texts)  # passwords never leak


def test_extract_text_sanitizes_invisible():
    xml = _XML.replace("password=\"true\"", "password=\"false\"")
    nodes = extract_text(xml)
    assert "\u200b" not in json.dumps(nodes)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_watch_server(events_home, monkeypatch):
    from droid_agent import watch
    monkeypatch.setattr(watch, "Adb", lambda *a, **k: FakeAdb())
    events.emit("tap", x=1, y=2, label="Allow")
    port = _free_port()
    t = threading.Thread(
        target=watch.serve,
        kwargs=dict(serial=None, port=port, force_mjpeg=True,
                    open_browser=False),
        daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            urllib.request.urlopen(f"{base}/healthz", timeout=2)
            break
        except OSError:
            time.sleep(0.1)
    else:
        pytest.fail("watch server never came up")

    html = urllib.request.urlopen(f"{base}/", timeout=3).read().decode()
    assert "droid-agent" in html and "jmuxer" in html

    js = urllib.request.urlopen(f"{base}/static/jmuxer.min.js", timeout=3)
    assert js.status == 200 and len(js.read()) > 10000

    meta = json.loads(urllib.request.urlopen(f"{base}/meta", timeout=3).read())
    assert meta["w"] == 1080 and meta["model"] == "PixelFake"
    assert meta["mode"] == "mjpeg"

    png = urllib.request.urlopen(f"{base}/frame.png", timeout=3).read()
    assert png.startswith(b"\x89PNG")

    # SSE: replay carries the pre-connect event
    resp = urllib.request.urlopen(f"{base}/events", timeout=3)
    seen = None
    for _ in range(40):
        line = resp.readline()
        if line.startswith(b"data:"):
            seen = json.loads(line[5:])
            break
        assert line, "SSE stream closed"
    assert seen["kind"] == "tap"

    # MJPEG: first bytes are the multipart boundary + a PNG frame
    mj = urllib.request.urlopen(f"{base}/mjpeg", timeout=4)
    chunk = mj.read(256)
    assert b"--f" in chunk or b"\x89PNG" in chunk


def test_cli_parse():
    from droid_agent.cli import build_parser
    p = build_parser()
    a = p.parse_args(["watch", "--port", "9000", "--mjpeg", "--no-open"])
    assert (a.port, a.mjpeg, a.no_open, a.host) == (9000, True, True, "127.0.0.1")
    a = p.parse_args(["unlock", "--pin", "1234"])
    assert a.pin == "1234"
    assert p.parse_args(["read"]).command == "read"
