"""Adversarial tests for droid-agent: garbage in, stack traces out?

Run:  PYTHONPATH=src python -m pytest tests_adversarial -q
"""
import json
import os
import subprocess
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from droid_agent import cli, session as sess
from droid_agent.actions import Actions, parse_target
from droid_agent.adb import Adb, AdbError, find_adb
from droid_agent.device import DeviceOps
from droid_agent.ui import parse_hierarchy

H = '<?xml version="1.0" encoding="UTF-8"?>'


def node(**kw):
    attrs = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in kw.items())
    return f"<node {attrs}/>"


# ---------------------------------------------------------------------------
# 1. parse_hierarchy vs malformed / weird dumps
# ---------------------------------------------------------------------------

class TestParseGarbage:
    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_hierarchy("")

    def test_garbage_text_raises(self):
        with pytest.raises(ValueError):
            parse_hierarchy("this is not xml at all")

    def test_xml_no_hierarchy_raises(self):
        with pytest.raises(ValueError):
            parse_hierarchy("<other><x/></other>")

    def test_noise_before_xml_survives(self):
        """'UI hierchary dumped to: ...' noise before <hierarchy is sliced off."""
        xml = "UI hierchary dumped to: /sdcard/x.xml\n" + H + \
            '\n<hierarchy><node text="hi" class="a.TextView" bounds="[0,0][100,100]"/></hierarchy>'
        els = parse_hierarchy(xml)
        assert len(els) == 1

    def test_truncated_xml(self):
        with pytest.raises(Exception):
            parse_hierarchy("<hierarchy><node")

    def test_zero_area_element_silently_dropped(self):
        """bounds='[0,0][0,0]' clickable button: vanishes from dump entirely
        (w<8 filter) — user never knows it existed."""
        xml = H + ('<hierarchy><node class="android.widget.Button" '
                   'clickable="true" bounds="[0,0][0,0]"/></hierarchy>')
        assert parse_hierarchy(xml) == []

    def test_negative_bounds_element_dropped(self):
        """unparseable bounds -> (0,0,0,0) -> below 8px floor -> dropped."""
        xml = H + ('<hierarchy><node class="android.widget.Button" '
                   'clickable="true" bounds="[-10,-10][100,100]"/></hierarchy>')
        assert parse_hierarchy(xml) == []

    def test_missing_bounds_element_dropped(self):
        """A clickable button with NO bounds attr is silently invisible."""
        xml = H + ('<hierarchy><node class="android.widget.Button" '
                   'clickable="true"/></hierarchy>')
        assert parse_hierarchy(xml) == []

    def test_inverted_bounds_dropped(self):
        xml = H + ('<hierarchy><node class="android.widget.Button" '
                   'clickable="true" bounds="[100,100][0,0]"/></hierarchy>')
        assert parse_hierarchy(xml) == []

    def test_missing_class_attr(self):
        xml = H + '<hierarchy><node clickable="true" bounds="[0,0][90,90]"/></hierarchy>'
        [el] = parse_hierarchy(xml)
        assert el.kind == "button"
        assert el.label == ""  # no text/desc/class -> empty label ref

    def test_emoji_label_parsed(self):
        xml = H + ('<hierarchy><node text="ok &#128512;" class="a.Button" '
                   'clickable="true" bounds="[0,0][90,90]"/></hierarchy>')
        [el] = parse_hierarchy(xml)
        assert "\U0001f600" in el.label

    def test_huge_label(self):
        big = "x" * 10000
        xml = H + (f'<hierarchy><node text="{big}" class="a.TextView" '
                   'bounds="[0,0][90,90]"/></hierarchy>')
        [el] = parse_hierarchy(xml)
        assert len(el.label) <= 200  # bounded

    def test_5000_nodes_performance(self):
        inner = "".join(
            node(text=f"r{i}", resource_id="", **{"class": "a.TextView",
                 "bounds": "[0,0][100,100]"})
            for i in range(5000))
        xml = H + f'<hierarchy><node class="a.FrameLayout" bounds="[0,0][10,10]">{inner}</node></hierarchy>'
        t0 = time.time()
        els = parse_hierarchy(xml)
        dt = time.time() - t0
        assert len(els) == 5000
        print(f"\n5000-node parse: {dt:.2f}s")
        assert dt < 10

    def test_deep_nesting_recursion(self):
        depth = 1500
        xml = H + "<hierarchy>" + '<node class="a.L" bounds="[0,0][10,10]">' * depth \
              + '<node text="leaf" class="a.T" bounds="[0,0][10,10]"/>' \
              + "</node>" * depth + "</hierarchy>"
        with pytest.raises(ValueError, match="too deep"):
            parse_hierarchy(xml)

    def test_password_never_leaks_plaintext(self):
        xml = H + ('<hierarchy><node class="android.widget.EditText" '
                   'password="true" text="hunter2" bounds="[0,0][90,90]"/></hierarchy>')
        [el] = parse_hierarchy(xml)
        assert el.password
        assert "hunter2" not in el.text + el.label + el.desc
        from droid_agent.ui import element_summary
        s = element_summary(el)
        assert "hunter2" not in s["text"] + s["label"] + s["desc"]

    def test_password_child_leaks_into_clickable_parent_label(self):
        """STILL BROKEN (ui.py): a clickable container wrapping a password
        field harvests the child's text via _collect_label BEFORE the
        password mask is applied — 'hunter2' lands in the parent's label
        and text, and from there into session.json / --json output."""
        xml = H + ('<hierarchy><node class="a.L" clickable="true" '
                   'bounds="[0,0][90,90]">'
                   '<node class="android.widget.EditText" password="true" '
                   'text="hunter2" bounds="[0,0][80,80]"/>'
                   "</node></hierarchy>")
        [el] = parse_hierarchy(xml)
        # FIXED: _collect_label skips password-marked descendants
        assert "hunter2" not in el.label + el.text + el.desc

    def test_label_from_deep_descendant(self):
        xml = H + ('<hierarchy><node class="a.L" clickable="true" bounds="[0,0][90,90]">'
                   '<node class="a.X" bounds="[0,0][10,10]">'
                   '<node class="a.Y" bounds="[0,0][10,10]">'
                   '<node text="deep" class="a.T" bounds="[0,0][10,10]"/>'
                   "</node></node></node></hierarchy>")
        [el] = parse_hierarchy(xml)
        assert el.label == "deep"

    def test_custom_edittext_kept(self):
        """custom views ending in EditText are inputs too (substring match)."""
        xml = H + ('<hierarchy><node class="com.x.MyEditText" '
                   'bounds="[0,0][90,90]"/></hierarchy>')
        [el] = parse_hierarchy(xml)
        assert el.kind == "input"

    def test_scrollable_container_label_not_stolen(self):
        xml = H + ('<hierarchy><node class="a.ScrollView" scrollable="true" '
                   'bounds="[0,0][900,900]">'
                   '<node text="child" class="a.T" bounds="[0,0][90,90]"/>'
                   "</node></hierarchy>")
        els = parse_hierarchy(xml)
        assert els[0].label == "scrollview"


# ---------------------------------------------------------------------------
# 2. parse_target edge cases
# ---------------------------------------------------------------------------

class TestParseTarget:
    def test_zero_ref(self):
        assert parse_target("0") == ("ref", (0, 0))  # ref 0 -> later 'no element'

    def test_negative_coords_rejected(self):
        with pytest.raises(AdbError):
            parse_target("-5,-5")

    def test_whitespace_target(self):
        with pytest.raises(AdbError):
            parse_target("   ")

    def test_trailing_comma(self):
        with pytest.raises(AdbError):
            parse_target("10,")

    def test_int_passthrough(self):
        assert parse_target(3) == ("ref", (3, 0))

    def test_tab_separated_xy(self):
        assert parse_target("10\t20") == ("xy", (10, 20))


# ---------------------------------------------------------------------------
# 3. session corruption shapes
# ---------------------------------------------------------------------------

class TestSessionCorruption:
    def _write(self, tmp_path, monkeypatch, obj):
        monkeypatch.setenv("DROID_AGENT_HOME", str(tmp_path))
        p = os.path.join(str(tmp_path), "session.json")
        with open(p, "w") as fh:
            fh.write(obj if isinstance(obj, str) else json.dumps(obj))

    def test_elements_not_list_tap_clean_error(self, tmp_path, monkeypatch):
        self._write(tmp_path, monkeypatch, {"device": "d", "dumped_at": time.time(),
                                            "elements": "oops"})
        s = sess.load()
        assert s.elements == []
        with pytest.raises(AdbError):
            Actions(_Fake()).tap("1", s)

    def test_element_missing_center_clean_error(self, tmp_path, monkeypatch):
        self._write(tmp_path, monkeypatch, {"device": "d", "dumped_at": time.time(),
                                            "elements": [{"ref": 1}]})
        with pytest.raises(AdbError):
            Actions(_Fake()).tap("1", sess.load())

    def test_top_level_list_load_returns_none(self, tmp_path, monkeypatch):
        self._write(tmp_path, monkeypatch, [1, 2, 3])
        assert sess.load() is None

    def test_elements_null_loads_empty(self, tmp_path, monkeypatch):
        self._write(tmp_path, monkeypatch, {"device": "d", "dumped_at": 1, "elements": None})
        s = sess.load()
        assert s.elements == []
        assert sess.resolve_ref(s, 1) is None

    def test_center_not_a_pair_still_tracebacks(self, tmp_path, monkeypatch):
        """STILL BROKEN: load() keeps dict elements but never validates
        `center`; {"ref":1,"center":null} makes tap() unpack None ->
        TypeError -> main() only catches AdbError -> raw traceback."""
        self._write(tmp_path, monkeypatch, {"device": "d", "dumped_at": 1e18,
                                            "elements": [{"ref": 1, "center": None}]})
        with pytest.raises(AdbError):
            Actions(_Fake()).tap("1", sess.load())
        self._write(tmp_path, monkeypatch, {"device": "d", "dumped_at": 1e18,
                                            "elements": [{"ref": 1, "center": "ab"}]})
        with pytest.raises(AdbError):
            Actions(_Fake()).tap("1", sess.load())

    def test_concurrent_save_race_windows(self, tmp_path, monkeypatch):
        """os.replace on Windows raises PermissionError when another process
        holds session.json open — a racing `dump` can CRASH outright."""
        monkeypatch.setenv("DROID_AGENT_HOME", str(tmp_path))
        errors = []

        def writer(tag):
            for _ in range(50):
                try:
                    sess.save(sess.Session(device=tag, dumped_at=time.time(),
                                           elements=[{"ref": 1, "center": [1, 1]}]))
                except Exception as e:
                    errors.append(("save", type(e).__name__))

        def reader():
            for _ in range(200):
                try:
                    sess.load()
                except Exception as e:
                    errors.append(("load", type(e).__name__))

        ts = [threading.Thread(target=writer, args=(t,)) for t in "ab"] + \
             [threading.Thread(target=reader) for _ in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        # On Windows, concurrent writers collide on session.json.tmp ->
        # PermissionError. This test DOCUMENTS the race; it "passes" only
        # because we record instead of assert. Print for the report.
        print(f"\nconcurrent save/load errors: {errors[:5]} ({len(errors)} total)")

    def test_tmp_file_collision(self, tmp_path, monkeypatch):
        """All writers share session.json.tmp — two dumps racing can
        interleave tmp writes then one replace fails."""
        monkeypatch.setenv("DROID_AGENT_HOME", str(tmp_path))
        import unittest.mock as mock
        real_open = open
        calls = []

        def slow_open(path, *a, **kw):
            fh = real_open(path, *a, **kw)
            if str(path).endswith(".tmp") and "w" in (a[0] if a else kw.get("mode", "r")):
                calls.append(path)
                time.sleep(0.05)
            return fh

        errs = []
        def w(tag):
            with mock.patch("builtins.open", slow_open):
                try:
                    sess.save(sess.Session(device=tag, dumped_at=1, elements=[]))
                except Exception as e:
                    errs.append(type(e).__name__)
        ts = [threading.Thread(target=w, args=(t,)) for t in "ab"]
        for t in ts: t.start()
        for t in ts: t.join()
        print(f"\ntmp collision: errs={errs}")
        # not asserting — both MAY succeed serially; the point is the shared tmp name


class _Fake:
    def __init__(self, serial=None):
        self.serial = serial
        self.calls = []

    def shell(self, cmd, timeout=None):
        self.calls.append(cmd)
        return ""


# ---------------------------------------------------------------------------
# 4. adb.run with canned weird subprocess results
# ---------------------------------------------------------------------------

class _Proc:
    def __init__(self, rc=0, out=b"", err=b""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def _adb_with(monkeypatch, proc=None, raises=None):
    def fake_init(self, serial=None, adb_path=None, timeout=5):
        self.serial = serial
        self.adb_path = "fake-adb"
        self.timeout = timeout
    monkeypatch.setattr(Adb, "__init__", fake_init)

    def fake_run(*a, **kw):
        if raises:
            raise raises
        return proc
    monkeypatch.setattr(subprocess, "run", fake_run)
    return Adb()


class TestAdbWeirdness:
    def test_error_on_stdout_rc0(self, monkeypatch):
        """adb prints 'error: closed' to STDOUT with rc=0 — now detected."""
        adb = _adb_with(monkeypatch, _Proc(rc=0, out=b"error: closed\n"))
        with pytest.raises(AdbError):
            adb.shell("input tap 1 1")

    def test_stdout_error_not_at_start_missed(self, monkeypatch):
        """only checks startswith('error:') — 'x error: y' slips through."""
        adb = _adb_with(monkeypatch, _Proc(rc=0, out=b"some error: thing\n"))
        assert adb.shell("x") == "some error: thing\n"

    def test_devices_unauthorized_state(self, monkeypatch):
        out = (b"List of devices attached\n"
               b"ABC123\tunauthorized transport_id:1\n"
               b"DEF456\toffline\n"
               b"GHI789\tno permissions (user in plugdev group; are your udev rules wrong?)\n")
        adb = _adb_with(monkeypatch, _Proc(rc=0, out=out))
        devs = adb.devices()
        # multi-word states keep the whole phrase now
        assert devs[0].state == "unauthorized"
        assert devs[1].state == "offline"
        assert devs[2].state == ("no permissions (user in plugdev group; "
                                 "are your udev rules wrong?)")
        with pytest.raises(AdbError):
            adb.require_device()

    def test_stderr_error_rc0_detected(self, monkeypatch):
        adb = _adb_with(monkeypatch, _Proc(rc=0, out=b"", err=b"error: closed"))
        with pytest.raises(AdbError):
            adb.shell("getprop ro.product.model")

    def test_timeout_wrapped(self, monkeypatch):
        adb = _adb_with(monkeypatch, raises=subprocess.TimeoutExpired("adb", 30))
        with pytest.raises(AdbError):
            adb.devices()

    def test_filenotfound_wrapped(self, monkeypatch):
        adb = _adb_with(monkeypatch, raises=FileNotFoundError("no adb"))
        with pytest.raises(AdbError):
            adb.devices()

    def test_oserror_wrapped(self, monkeypatch):
        adb = _adb_with(monkeypatch, raises=OSError("not a valid win32 app"))
        with pytest.raises(AdbError):
            adb.devices()

    def test_screencap_non_png(self, monkeypatch):
        adb = _adb_with(monkeypatch, _Proc(rc=0, out=b"not a png"))
        with pytest.raises(AdbError, match="PNG"):
            DeviceOps(adb).screenshot()

    def test_dump_empty_cat(self, monkeypatch):
        adb = _adb_with(monkeypatch, _Proc(rc=0, out=b""))
        with pytest.raises(AdbError):
            DeviceOps(adb).dump_ui_xml()

    def test_disconnect_no_port_sends_host_only(self, monkeypatch):
        sent = []
        adb = _adb_with(monkeypatch, _Proc(rc=0, out=b""))
        monkeypatch.setattr(Adb, "run",
                            lambda self, *a, **kw: sent.append(a) or "")
        adb.disconnect("1.2.3.4", None)
        assert sent[0] == ("disconnect", "1.2.3.4")


# ---------------------------------------------------------------------------
# 5. find_adb
# ---------------------------------------------------------------------------

class TestFindAdb:
    def test_explicit_missing_path_errors(self, monkeypatch, tmp_path):
        """--adb <nonexistent> fails loudly instead of falling back."""
        monkeypatch.setattr("shutil.which", lambda _x: "C:/real/adb.exe")
        with pytest.raises(AdbError):
            find_adb("C:/nonexistent/adb.exe")

    def test_nothing_found_raises_adberror(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _x: None)
        monkeypatch.setattr("os.path.isfile", lambda p: False)
        monkeypatch.delenv("ANDROID_HOME", raising=False)
        monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
        with pytest.raises(AdbError):
            find_adb("definitely-not-real.exe")


# ---------------------------------------------------------------------------
# 6. CLI-level
# ---------------------------------------------------------------------------

class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _stub_adb(monkeypatch, shell_out="", devices=None):
    def fake_init(self, serial=None, adb_path=None, timeout=5):
        self.serial = serial
        self.adb_path = "fake-adb"
        self.timeout = timeout
        self._shell_out = shell_out
    monkeypatch.setattr(Adb, "__init__", fake_init)
    monkeypatch.setattr(Adb, "require_device", lambda self: None)
    monkeypatch.setattr(Adb, "shell",
                        lambda self, c, timeout=None: self._shell_out)


class TestCli:
    def test_json_error_envelope(self, capsys, monkeypatch, tmp_path):
        monkeypatch.setenv("DROID_AGENT_HOME", str(tmp_path))
        _stub_adb(monkeypatch)
        rc = cli.main(["--json", "tap", "77"])
        assert rc == 1
        payload = json.loads(capsys.readouterr().out)
        assert "error" in payload

    def test_swipe_bare_usage_error(self, monkeypatch, capsys):
        _stub_adb(monkeypatch)
        rc = cli.main(["swipe"])
        assert rc == 1

    def test_swipe_4coords(self, monkeypatch):
        sent = []
        _stub_adb(monkeypatch)
        monkeypatch.setattr(Adb, "shell",
                            lambda self, c, timeout=None: sent.append(c) or "")
        rc = cli.main(["swipe", "100", "200", "300", "400"])
        assert rc == 0
        assert sent == ["input swipe 100 200 300 400 300"]

    def test_swipe_mixed_direction_and_coords(self, monkeypatch, capsys):
        """`swipe up 10 20 30` -> 'coordinates must be integers' (misleading)."""
        _stub_adb(monkeypatch)
        rc = cli.main(["swipe", "up", "10", "20", "30"])
        assert rc == 1

    def test_swipe_negative_coords_pass_to_device(self, monkeypatch):
        sent = []
        _stub_adb(monkeypatch)
        monkeypatch.setattr(Adb, "shell",
                            lambda self, c, timeout=None: sent.append(c) or "")
        rc = cli.main(["swipe", "-1", "-2", "300", "400"])
        # negative coords are now rejected before reaching the device
        assert rc == 1
        assert sent == []

    def test_connect_bad_port_clean_error(self):
        with pytest.raises(AdbError):
            cli.cmd_connect(_Args(target="h:zz", serial=None, adb=None, json=False))

    def test_connect_colon_only_clean_error(self):
        with pytest.raises(AdbError):
            cli.cmd_connect(_Args(target=":", serial=None, adb=None, json=False))

    def test_pair_no_port_clean_error(self):
        rc = cli.cmd_pair(_Args(target="h", code="1",
                                serial=None, adb=None, json=False))
        assert rc == 1

    def test_pair_failure_rc1(self, monkeypatch):
        monkeypatch.setattr(Adb, "__init__",
                            lambda self, **kw: None or setattr(self, "x", 1))
        monkeypatch.setattr(Adb, "pair",
                            lambda self, h, p, c: "Failed: wrong code")
        rc = cli.cmd_pair(_Args(target="h:1", code="000000",
                                serial=None, adb=None, json=False))
        assert rc == 1

    def test_shell_no_args_usage_error(self, monkeypatch, capsys):
        _stub_adb(monkeypatch, shell_out="")
        rc = cli.main(["shell"])
        assert rc == 1

    def test_open_shell_injection_blocked(self):
        """package arg is allowlist-validated — injection can't reach sh."""
        f = _Fake()
        with pytest.raises(AdbError):
            DeviceOps(f).launch("com.x; echo PWNED")
        assert f.calls == []

    def test_close_shell_injection_blocked(self):
        f = _Fake()
        with pytest.raises(AdbError):
            DeviceOps(f).force_stop("x; echo PWNED")
        assert f.calls == []

    def test_install_local_path_unquoted(self, monkeypatch):
        """apk path goes to `adb install` as argv — spaces are safe and the
        path is never shell-interpolated."""
        adb = _adb_with(monkeypatch)
        sent = []
        monkeypatch.setattr(Adb, "run",
                            lambda self, *a, **kw: sent.append(a) or "")
        DeviceOps(adb).install("my apk; rm -rf")
        assert sent[0] == ("install", "my apk; rm -rf")  # argv, not shell

    def test_type_apostrophe_not_escaped(self):
        """it's -> input text "it's" — ' needs no escape inside ""."""
        f = _Fake()
        Actions(f).type_text("it's")
        assert f.calls[0] == 'input text "it\'s"'

    def test_type_percent_s_warns(self):
        """literal '100%s' -> device would insert a space; now the caller is
        warned via the returned warnings list."""
        f = _Fake()
        warns = Actions(f).type_text("100%s")
        assert warns and "%s" in warns[0]
        # still sent — the warning is informational, not a block
        assert f.calls[0] == 'input text "100%s"'

    def test_type_newline_becomes_enter(self):
        """\\n is split into an Enter keyevent between text chunks."""
        f = _Fake()
        Actions(f).type_text("a\nb")
        assert f.calls == [
            'input text "a"',
            "input keyevent 66",
            'input text "b"',
        ]

    def test_key_numeric_bounded(self):
        f = _Fake()
        with pytest.raises(AdbError):
            Actions(f).key("999999")
        assert Actions(f).key("66") == 66

    def test_wait_negative_clamped(self):
        Actions(_Fake()).wait(-5)  # silently sleeps 0

    def test_mcp_missing_package_traceback(self, monkeypatch):
        """ImportError inside run() is NOT covered by the try/except."""
        import builtins
        real_import = builtins.__import__
        def blocker(name, *a, **kw):
            if name == "mcp" or name.startswith("mcp."):
                raise ModuleNotFoundError("No module named 'mcp'")
            return real_import(name, *a, **kw)
        monkeypatch.setattr(builtins, "__import__", blocker)
        monkeypatch.delitem(sys.modules, "mcp", raising=False)
        for k in list(sys.modules):
            if k.startswith("mcp"):
                sys.modules.pop(k)
        from droid_agent import mcp_server
        with pytest.raises(ModuleNotFoundError):
            mcp_server.run()


# ---------------------------------------------------------------------------
# 7. output.render_elements pathological labels
# ---------------------------------------------------------------------------

class TestRender:
    def test_newline_in_label_collapsed(self):
        """label whitespace is collapsed — 'a\\nb' renders as 'a b', one line."""
        from droid_agent.output import render_elements
        xml = H + ('<hierarchy><node text="a&#10;b" class="a.T" '
                   'bounds="[0,0][90,90]"/></hierarchy>')
        els = parse_hierarchy(xml)
        assert els[0].label == "a b"
        out = render_elements(els)
        assert "a b" in out
        assert out.count("\n") == 0  # single row, no spliced extra line

    def test_password_masked_in_render(self):
        from droid_agent.output import render_elements
        xml = H + ('<hierarchy><node class="android.widget.EditText" '
                   'password="true" text="secret" bounds="[0,0][90,90]"/></hierarchy>')
        out = render_elements(parse_hierarchy(xml))
        assert "secret" not in out

    def test_emoji_render_cp1252(self, capsys, monkeypatch):
        """dump output with emoji crashes print() on cp1252 consoles."""
        import io
        from droid_agent.output import render_elements
        xml = H + ('<hierarchy><node text="ok \U0001f600" class="a.T" '
                   'bounds="[0,0][90,90]"/></hierarchy>')
        out = render_elements(parse_hierarchy(xml))
        # main() reconfigures stdout to utf-8/errors=replace; a cp1252
        # fallback encode with replacement must never raise
        out.encode("cp1252", errors="replace")
