"""droid-agent CLI.

    droid-agent devices
    droid-agent connect 192.168.1.42:5555
    droid-agent dump            # numbered interactive elements
    droid-agent tap 3           # tap element #3 from the last dump
    droid-agent type "hola"     # into the focused field
    droid-agent swipe up
    droid-agent screenshot shot.png
    droid-agent open com.whatsapp
    droid-agent mcp             # stdio MCP server (needs [mcp] extra)
"""

from __future__ import annotations

import argparse
import json
import sys

from droid_agent import __version__
from droid_agent import session as sess
from droid_agent.actions import Actions
from droid_agent.adb import Adb, AdbError
from droid_agent.device import DeviceOps
from droid_agent.output import emit, render_elements
from droid_agent.ui import parse_hierarchy


def _adb(args) -> Adb:
    return Adb(serial=getattr(args, "serial", None),
               adb_path=getattr(args, "adb", None))


def _err(msg: str, args=None) -> int:
    if getattr(args, "json", False):
        json.dump({"error": msg}, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        sys.stderr.write(f"error: {msg}\n")
    return 1


def cmd_devices(args) -> int:
    devs = _adb(args).devices()
    if args.json:
        emit([d.__dict__ for d in devs], True)
        return 0
    if not devs:
        print("no devices attached")
        return 0
    for d in devs:
        model = f" {d.model}" if d.model else ""
        print(f"{d.serial:<24} {d.state:<14}{model}")
    return 0


def _parse_host_port(target: str, default_port: int = 5555
                     ) -> tuple:
    host, sep, port_s = target.partition(":")
    if not host:
        raise AdbError(f"need a host: `droid-agent connect <ip>[:port]`, "
                       f"got {target!r}")
    if not sep:
        return host, default_port
    if not port_s.isdigit() or not (0 < int(port_s) < 65536):
        raise AdbError(f"invalid port in {target!r}")
    return host, int(port_s)


def cmd_connect(args) -> int:
    host, port = _parse_host_port(args.target)
    out = _adb(args).connect(host, port)
    print(out)
    return 0 if "connected" in out or "already" in out else 1


def cmd_pair(args) -> int:
    host, port = _parse_host_port(args.target, default_port=0)
    if port == 0:
        return _err("pair needs the port from the pairing dialog: "
                    "droid-agent pair <ip>:<port> <code>", args)
    out = _adb(args).pair(host, port, args.code)
    print(out)
    ok = "success" in out.lower() or "paired" in out.lower()
    return 0 if ok else 1


def cmd_disconnect(args) -> int:
    if args.target:
        host, port = _parse_host_port(args.target)
        out = _adb(args).disconnect(host, port)
    else:
        out = _adb(args).disconnect()
    print(out or "done")
    return 0


def _dump(args, adb: Adb | None = None):
    adb = adb or _adb(args)
    adb.require_device()
    xml = DeviceOps(adb).dump_ui_xml()
    try:
        elements = parse_hierarchy(xml)
    except ValueError as e:
        raise AdbError(f"cannot parse UI hierarchy: {e}")
    session = sess.from_elements(adb.serial or "", elements)
    sess.save(session)
    return elements, session


def cmd_dump(args) -> int:
    elements, session = _dump(args)
    if args.json:
        emit(session.elements, True)
        return 0
    print(render_elements(elements))
    print(f"\n{len(elements)} elements · tap with `droid-agent tap <ref>`")
    return 0


def _session_for(args, adb: Adb) -> sess.Session | None:
    s = sess.load()
    if s and s.device and adb.serial and s.device != adb.serial:
        if not args.json:
            print(f"(note: refs are from device {s.device}, not "
                  f"{adb.serial} — run `droid-agent dump` again)",
                  file=sys.stderr)
        return None
    if s and s.is_stale and not args.json:
        print(f"(note: dump is {int(s.stale_seconds)}s old — "
              f"refs may have moved, `droid-agent dump` to refresh)",
              file=sys.stderr)
    return s


def cmd_tap(args) -> int:
    adb = _adb(args)
    adb.require_device()
    session = _session_for(args, adb)
    x, y = Actions(adb).tap(args.target, session)
    if args.json:
        emit({"action": "tap", "x": x, "y": y}, True)
    else:
        print(f"tapped ({x}, {y})")
    return 0


def cmd_long_press(args) -> int:
    adb = _adb(args)
    adb.require_device()
    session = _session_for(args, adb)
    x, y = Actions(adb).long_press(args.target, max(0, args.ms), session)
    if args.json:
        emit({"action": "long-press", "x": x, "y": y, "ms": args.ms}, True)
    else:
        print(f"long-pressed ({x}, {y}) {args.ms}ms")
    return 0


def cmd_swipe(args) -> int:
    adb = _adb(args)
    adb.require_device()
    ops = DeviceOps(adb)
    acts = Actions(adb)
    positionals = [v for v in
                   (args.direction, args.x1, args.y1, args.x2, args.y2)
                   if v is not None]
    if len(positionals) == 1 and positionals[0] in ("up", "down", "left", "right"):
        distance = min(1.0, max(0.0, args.distance))
        ms = max(0, args.ms)
        x1, y1, x2, y2 = acts.swipe_dir(
            positionals[0], ops.screen_size(), distance, ms)
    elif len(positionals) == 4:
        if positionals[0] in ("up", "down", "left", "right"):
            return _err(
                "swipe takes either a direction OR x1 y1 x2 y2, not both",
                args)
        try:
            coords = [int(v) for v in positionals]
        except ValueError:
            return _err("swipe coordinates must be integers", args)
        if any(c < 0 for c in coords):
            return _err("swipe coordinates must be >= 0", args)
        x1, y1, x2, y2 = acts.swipe(*coords, duration_ms=max(0, args.ms))
    else:
        return _err(
            "usage: swipe up|down|left|right  OR  swipe x1 y1 x2 y2", args)
    if args.json:
        emit({"action": "swipe", "from": [x1, y1], "to": [x2, y2]}, True)
    else:
        print(f"swiped ({x1},{y1}) -> ({x2},{y2})")
    return 0


def cmd_type(args) -> int:
    adb = _adb(args)
    adb.require_device()
    warnings = Actions(adb).type_text(args.text, clear=args.clear)
    if args.json:
        emit({"action": "type", "chars": len(args.text),
              "warnings": warnings}, True)
    else:
        for w in warnings:
            print(f"warning: {w}", file=sys.stderr)
        print(f"typed {len(args.text)} chars")
    return 0


def cmd_key(args) -> int:
    adb = _adb(args)
    adb.require_device()
    code = Actions(adb).key(args.name)
    if args.json:
        emit({"action": "key", "keyevent": code}, True)
    else:
        print(f"key {args.name} ({code})")
    return 0


def cmd_wait(args) -> int:
    Actions(_adb(args)).wait(args.seconds)
    return 0


def cmd_open(args) -> int:
    adb = _adb(args)
    adb.require_device()
    out = DeviceOps(adb).launch(args.package, args.activity)
    if args.json:
        emit({"action": "open", "package": args.package}, True)
    else:
        print(f"launched {args.package}")
        if "Warning" in out or "Error" in out:
            sys.stderr.write(out.strip() + "\n")
    return 0


def cmd_close(args) -> int:
    adb = _adb(args)
    adb.require_device()
    DeviceOps(adb).force_stop(args.package)
    if args.json:
        emit({"action": "close", "package": args.package}, True)
    else:
        print(f"stopped {args.package}")
    return 0


def cmd_install(args) -> int:
    adb = _adb(args)
    adb.require_device()
    out = DeviceOps(adb).install(args.apk, reinstall=args.reinstall)
    print(out)
    return 0 if "Success" in out else 1


def cmd_uninstall(args) -> int:
    adb = _adb(args)
    adb.require_device()
    print(DeviceOps(adb).uninstall(args.package))
    return 0


def cmd_screenshot(args) -> int:
    adb = _adb(args)
    adb.require_device()
    png = DeviceOps(adb).screenshot()
    out = args.output or "screenshot.png"
    try:
        with open(out, "wb") as fh:
            fh.write(png)
    except OSError as e:
        return _err(f"cannot write {out}: {e}", args)
    if args.json:
        emit({"action": "screenshot", "path": out, "bytes": len(png)}, True)
    else:
        print(f"saved {out} ({len(png)//1024} KB)")
    return 0


def cmd_state(args) -> int:
    adb = _adb(args)
    adb.require_device()
    st = DeviceOps(adb).state()
    if args.json:
        emit(st.__dict__, True)
        return 0
    print(f"model      {st.model} (sdk {st.sdk})")
    print(f"screen     {st.screen_size[0]}x{st.screen_size[1]} "
          f"({'on' if st.screen_on else 'off'})")
    print(f"foreground {st.foreground_package}/{st.foreground_activity}")
    return 0


def cmd_shell(args) -> int:
    if not args.cmd:
        return _err("usage: droid-agent shell <command>", args)
    adb = _adb(args)
    adb.require_device()
    print(adb.shell(" ".join(args.cmd)), end="")
    return 0


def cmd_mcp(args) -> int:
    try:
        from droid_agent.mcp_server import run
        run(serial=args.serial)
    except ImportError:
        return _err("MCP support not installed: pip install 'droid-agent[mcp]'", args)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="droid-agent",
        description="Agent-native Android control over stock adb. "
                    "No Appium, no on-device APK.",
    )
    p.add_argument("-V", "--version", action="version",
                   version=f"droid-agent {__version__}")
    p.add_argument("-s", "--serial", help="device serial (from `devices`)")
    p.add_argument("--adb", help="path to adb binary")
    p.add_argument("--json", action="store_true",
                   help="machine-readable output (recommended for agents)")
    sub = p.add_subparsers(dest="command", required=True)

    # accept --json after the subcommand too (droid-agent dump --json);
    # SUPPRESS default so the subparser doesn't reset the global value
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true",
                        default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    def sub_(name, fn, **kw):
        sp = sub.add_parser(name, parents=[common], **kw)
        sp.set_defaults(func=fn)
        return sp

    sub_("devices", cmd_devices, help="list attached devices")
    c = sub_("connect", cmd_connect, help="adb connect <host>:<port>")
    c.add_argument("target")
    c = sub_("pair", cmd_pair, help="Android 11+ wireless pairing")
    c.add_argument("target", help="host:port shown in the pairing dialog")
    c.add_argument("code", help="6-digit pairing code")
    c = sub_("disconnect", cmd_disconnect, help="disconnect a device")
    c.add_argument("target", nargs="?")
    sub_("dump", cmd_dump, help="numbered interactive elements")
    c = sub_("tap", cmd_tap, help="tap element ref or x,y")
    c.add_argument("target")
    c = sub_("long-press", cmd_long_press, help="long-press ref or x,y")
    c.add_argument("target")
    c.add_argument("--ms", type=int, default=800)
    c = sub_("swipe", cmd_swipe, help="swipe up/down/left/right or x1 y1 x2 y2")
    c.add_argument("direction", nargs="?")
    c.add_argument("x1", type=int, nargs="?")
    c.add_argument("y1", type=int, nargs="?")
    c.add_argument("x2", type=int, nargs="?")
    c.add_argument("y2", type=int, nargs="?")
    c.add_argument("--distance", type=float, default=0.6)
    c.add_argument("--ms", type=int, default=300)
    c = sub_("type", cmd_type, help="type text into the focused field")
    c.add_argument("text")
    c.add_argument("--clear", action="store_true",
                   help="clear the field first (long-press delete)")
    c = sub_("key", cmd_key, help="send keyevent (back/home/enter/...)")
    c.add_argument("name", help="key name or numeric keyevent code")
    c = sub_("wait", cmd_wait, help="sleep N seconds")
    c.add_argument("seconds", type=float)
    c = sub_("open", cmd_open, help="launch an app by package name")
    c.add_argument("package")
    c.add_argument("--activity")
    c = sub_("close", cmd_close, help="force-stop an app")
    c.add_argument("package")
    c = sub_("install", cmd_install, help="install an apk")
    c.add_argument("apk")
    c.add_argument("--reinstall", action="store_true")
    c = sub_("uninstall", cmd_uninstall, help="uninstall a package")
    c.add_argument("package")
    c = sub_("screenshot", cmd_screenshot, help="save a PNG screenshot")
    c.add_argument("output", nargs="?")
    sub_("state", cmd_state, help="foreground app, screen, device info")
    c = sub_("shell", cmd_shell, help="raw adb shell escape hatch")
    c.add_argument("cmd", nargs=argparse.REMAINDER)
    sub_("mcp", cmd_mcp, help="run the stdio MCP server (droid-agent[mcp])")
    return p


def main(argv: list[str] | None = None) -> int:
    # cp1252 consoles crash on emoji/unicode labels — force utf-8 out
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except AdbError as e:
        return _err(str(e), args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
