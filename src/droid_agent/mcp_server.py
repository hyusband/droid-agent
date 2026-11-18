"""MCP server: expose every device primitive as a tool for AI agents.

Run:  droid-agent mcp
Then register it in Claude Code / Cursor / Devin / Codex:

    {"mcpServers": {"droid-agent": {"command": "droid-agent", "args": ["mcp"]}}}
"""

from __future__ import annotations

import base64
import json
import time

from droid_agent import session as sess
from droid_agent.actions import Actions
from droid_agent.adb import Adb
from droid_agent.device import DeviceOps
from droid_agent.ui import (
    Element,
    element_summary,
    find_elements,
    parse_hierarchy,
)

_MAX_OUT = 20_000


def _mk(serial: str | None):
    adb = Adb(serial=serial)
    return adb, DeviceOps(adb), Actions(adb)


def _err(msg: str) -> str:
    return json.dumps({"error": msg})


def _trunc(out: str, cap: int = _MAX_OUT) -> str:
    return out[:cap] + f"\n… [truncated {len(out) - cap} chars]" if len(out) > cap else out


def run(serial: str | None = None) -> None:
    from mcp.server.fastmcp import FastMCP  # optional dep

    try:
        from mcp.server.fastmcp import Image
    except ImportError:  # very old mcp SDKs: fall back to base64 text
        Image = None  # type: ignore[assignment]

    mcp = FastMCP("droid-agent")

    def _dump() -> tuple[Adb, list[Element]]:
        """Fresh dump: parses, persists the session refs, returns elements."""
        adb, ops, _ = _mk(serial)
        elements = parse_hierarchy(ops.dump_ui_xml())
        sess.save(sess.from_elements(adb.serial or "", elements))
        return adb, elements

    # -- discovery -----------------------------------------------------

    @mcp.tool()
    def devices() -> str:
        """List attached Android devices (serial, state, model)."""
        adb, _, _ = _mk(serial)
        return json.dumps([d.__dict__ for d in adb.devices()])

    @mcp.tool()
    def dump_ui() -> str:
        """Dump the current screen as a numbered list of interactive
        elements (refs). Use the refs with tap/type_into/scroll calls."""
        _, elements = _dump()
        return json.dumps([element_summary(el) for el in elements])

    @mcp.tool()
    def find(
        text: str | None = None,
        kind: str | None = None,
        clickable: bool | None = None,
        editable: bool | None = None,
        exact: bool = False,
    ) -> str:
        """Search the current screen for elements matching text (substring
        on label/text/desc, case-insensitive — or exact match) plus
        optional kind/clickable/editable filters. Cheaper than reading a
        full dump when you know what you're looking for."""
        _, elements = _dump()
        hits = find_elements(elements, text, kind, clickable, editable, exact)
        return json.dumps([element_summary(el) for el in hits])

    @mcp.tool()
    def device_state() -> str:
        """Foreground app, screen size/state, model, sdk."""
        _, ops, _ = _mk(serial)
        return json.dumps(ops.state().__dict__)

    @mcp.tool()
    def logcat(lines: int = 200, filter: str = "") -> str:
        """Recent device logs (logcat -d), optionally substring-filtered
        case-insensitively. Use for crash/permission debugging."""
        adb, _, _ = _mk(serial)
        n = max(1, min(int(lines), 5000))
        out = adb.shell(f"logcat -d -t {n}")
        if filter:
            needle = filter.lower()
            out = "\n".join(
                line for line in out.splitlines() if needle in line.lower()
            )
        return _trunc(out)

    @mcp.tool()
    def list_packages(filter: str = "") -> str:
        """Installed packages on the device, optionally substring-filtered."""
        adb, _, _ = _mk(serial)
        out = adb.shell("pm list packages")
        names = [
            line.removeprefix("package:").strip()
            for line in out.splitlines()
            if line
        ]
        if filter:
            names = [n for n in names if filter.lower() in n.lower()]
        return json.dumps(names[:500])

    # -- actions --------------------------------------------------------

    @mcp.tool()
    def tap(ref: int) -> str:
        """Tap element #ref from the last dump_ui/find call."""
        adb, _, act = _mk(serial)
        el = sess.resolve_ref(sess.load(), ref)
        if not el:
            return _err(f"no element #{ref}; call dump_ui or find first")
        x, y = act.tap(ref, sess.load())
        return json.dumps({"tapped": ref, "x": x, "y": y, "label": el.get("label")})

    @mcp.tool()
    def tap_xy(x: int, y: int) -> str:
        """Tap raw coordinates."""
        _, _, act = _mk(serial)
        act.tap(f"{x},{y}")
        return json.dumps({"tapped": [x, y]})

    @mcp.tool()
    def tap_text(text: str, exact: bool = False) -> str:
        """Find a visible element by its text/label and tap it — the most
        common pattern ("tap the Allow button"). Clickable matches are
        preferred over plain text."""
        _, elements = _dump()
        hits = find_elements(elements, text=text, exact=exact)
        if not hits:
            return _err(f"no element matching {text!r} on screen")
        clickable = [el for el in hits if el.clickable]
        el = clickable[0] if clickable else hits[0]
        adb, _, act = _mk(serial)
        x, y = act.tap(f"{el.cx},{el.cy}")
        return json.dumps(
            {"tapped": el.ref, "x": x, "y": y, "label": el.label,
             "matches": len(hits)}
        )

    @mcp.tool()
    def long_press(ref: int, duration_ms: int = 800) -> str:
        """Long-press element #ref (context menus, selection mode)."""
        adb, _, act = _mk(serial)
        if not sess.resolve_ref(sess.load(), ref):
            return _err(f"no element #{ref}; call dump_ui or find first")
        x, y = act.long_press(ref, duration_ms, sess.load())
        return json.dumps({"long_pressed": ref, "x": x, "y": y, "ms": duration_ms})

    @mcp.tool()
    def type_text(text: str, clear: bool = False) -> str:
        """Type text into the currently focused field."""
        _, _, act = _mk(serial)
        warnings = act.type_text(text, clear=clear)
        return json.dumps({"typed": len(text), "warnings": warnings})

    @mcp.tool()
    def type_into(ref: int, text: str, clear: bool = True) -> str:
        """Tap input field #ref, then type text into it. Use for filling
        forms — no need to focus the field first."""
        adb, _, act = _mk(serial)
        el = sess.resolve_ref(sess.load(), ref)
        if not el:
            return _err(f"no element #{ref}; call dump_ui or find first")
        act.tap(ref, sess.load())
        warnings = act.type_text(text, clear=clear)
        return json.dumps(
            {"typed": len(text), "into": ref,
             "label": el.get("label"), "warnings": warnings}
        )

    @mcp.tool()
    def swipe(direction: str, distance: float = 0.6) -> str:
        """Swipe up/down/left/right (direction of content movement)."""
        adb, ops, act = _mk(serial)
        x1, y1, x2, y2 = act.swipe_dir(direction, ops.screen_size(), distance)
        return json.dumps({"from": [x1, y1], "to": [x2, y2]})

    @mcp.tool()
    def swipe_xy(x1: int, y1: int, x2: int, y2: int,
                 duration_ms: int = 300) -> str:
        """Raw swipe between two points — pinch-free gestures, sliders."""
        _, _, act = _mk(serial)
        act.swipe(x1, y1, x2, y2, duration_ms)
        return json.dumps({"from": [x1, y1], "to": [x2, y2], "ms": duration_ms})

    @mcp.tool()
    def scroll_until(text: str, direction: str = "up",
                     max_swipes: int = 10) -> str:
        """Scroll until an element matching `text` appears on screen.
        direction is the content-movement direction ("up" scrolls down
        the list). Returns the found element or an error."""
        swipes = max(1, min(int(max_swipes), 25))
        for i in range(swipes + 1):
            _, elements = _dump()
            hits = find_elements(elements, text=text)
            if hits:
                return json.dumps(
                    {"found": element_summary(hits[0]),
                     "swipes": i, "matches": len(hits)}
                )
            if i == swipes:
                break
            adb, ops, act = _mk(serial)
            act.swipe_dir(direction, ops.screen_size())
        return _err(f"{text!r} not found after {swipes} swipes")

    @mcp.tool()
    def key(name: str) -> str:
        """Send a key event: back/home/enter/tab/del/power/..."""
        _, _, act = _mk(serial)
        return json.dumps({"key": name, "keyevent": act.key(name)})

    @mcp.tool()
    def wait(seconds: float) -> str:
        """Sleep N seconds (let animations/loads settle)."""
        _, _, act = _mk(serial)
        act.wait(seconds)
        return json.dumps({"waited": seconds})

    @mcp.tool()
    def wait_for(text: str, timeout: float = 10.0) -> str:
        """Poll the screen until an element matching `text` appears
        (or `timeout` seconds elapse). Use after taps that trigger
        navigation/loading instead of a fixed wait."""
        deadline = time.monotonic() + max(0.5, min(timeout, 60.0))
        while True:
            _, elements = _dump()
            hits = find_elements(elements, text=text)
            if hits:
                return json.dumps(
                    {"found": element_summary(hits[0]), "matches": len(hits)}
                )
            if time.monotonic() >= deadline:
                return _err(f"{text!r} did not appear within {timeout}s")
            time.sleep(0.5)

    # -- apps & files ----------------------------------------------------

    @mcp.tool()
    def open_app(package: str) -> str:
        """Launch an app by package name."""
        _, ops, _ = _mk(serial)
        ops.launch(package)
        return json.dumps({"launched": package})

    @mcp.tool()
    def close_app(package: str) -> str:
        """Force-stop an app."""
        _, ops, _ = _mk(serial)
        ops.force_stop(package)
        return json.dumps({"stopped": package})

    @mcp.tool()
    def clear_data(package: str) -> str:
        """Wipe an app's data (pm clear) — fresh-start automation."""
        _, ops, _ = _mk(serial)
        return json.dumps({"cleared": package, "out": ops.clear(package)})

    @mcp.tool()
    def is_installed(package: str) -> str:
        """Check whether a package is installed."""
        _, ops, _ = _mk(serial)
        return json.dumps({"package": package, "installed": ops.is_installed(package)})

    @mcp.tool()
    def install(apk_path: str, reinstall: bool = False) -> str:
        """Install an APK from a local file path onto the device."""
        _, ops, _ = _mk(serial)
        return json.dumps({"installed": apk_path,
                           "out": ops.install(apk_path, reinstall)})

    @mcp.tool()
    def uninstall(package: str) -> str:
        """Uninstall an app by package name."""
        _, ops, _ = _mk(serial)
        return json.dumps({"uninstalled": package, "out": ops.uninstall(package)})

    @mcp.tool()
    def push_file(local: str, remote: str) -> str:
        """Push a local file to the device (e.g. /sdcard/Download/)."""
        adb, _, _ = _mk(serial)
        return json.dumps({"pushed": remote, "out": adb.push(local, remote)})

    @mcp.tool()
    def pull_file(remote: str, local: str) -> str:
        """Pull a file from the device to a local path."""
        adb, _, _ = _mk(serial)
        return json.dumps({"pulled": local, "out": adb.pull(remote, local)})

    # -- connectivity & escape hatches -----------------------------------

    @mcp.tool()
    def connect(host: str, port: int = 5555) -> str:
        """Connect to a device over wireless adb (host[:port])."""
        adb, _, _ = _mk(serial)
        return json.dumps({"out": adb.connect(host, port)})

    @mcp.tool()
    def disconnect(host: str | None = None) -> str:
        """Disconnect a wireless adb device (or all)."""
        adb, _, _ = _mk(serial)
        return json.dumps({"out": adb.disconnect(host)})

    @mcp.tool()
    def shell(cmd: str) -> str:
        """Run a raw `adb shell` command — escape hatch for anything the
        structured tools don't cover (dumpsys, settings get, input …)."""
        adb, _, _ = _mk(serial)
        if not cmd or not cmd.strip():
            return _err("empty command")
        return _trunc(adb.shell(cmd))

    if Image is not None:

        @mcp.tool()
        def screenshot():
            """Current screen as a PNG image (rendered by MCP clients —
            use it to visually verify state)."""
            _, ops, _ = _mk(serial)
            # returning an Image instance -> proper image content block
            return Image(data=ops.screenshot(), format="png")

    else:

        @mcp.tool()
        def screenshot() -> str:  # type: ignore[misc]
            """Current screen as base64 PNG."""
            _, ops, _ = _mk(serial)
            return base64.b64encode(ops.screenshot()).decode()

    # -- guidance ---------------------------------------------------------

    @mcp.prompt()
    def android_task(task: str) -> str:
        """Recommended loop for driving the device: dump → act → verify."""
        return (
            f"Task on the Android device: {task}\n\n"
            "Use this loop — do NOT guess coordinates:\n"
            "1. `find` or `dump_ui` to see actionable elements (numbered refs)\n"
            "2. Act: `tap`/`tap_text`, `type_into` for fields, `swipe`/\n"
            "   `scroll_until` for lists, `key back` to go back\n"
            "3. Verify: `wait_for` the expected text, or `find`/`screenshot`\n"
            "4. Refs go stale on navigation — dump again after each action\n"
            "5. Escape hatch: `shell` for raw adb commands, `logcat` for crashes"
        )

    mcp.run()
