"""MCP server: expose every device primitive as a tool for AI agents.

Run:  droid-agent mcp
Then register it in Claude Code / Cursor / Devin / Codex:

    {"mcpServers": {"droid-agent": {"command": "droid-agent", "args": ["mcp"]}}}
"""

from __future__ import annotations

import base64
import json
from typing import Optional

from droid_agent import session as sess
from droid_agent.actions import Actions
from droid_agent.adb import Adb
from droid_agent.device import DeviceOps
from droid_agent.ui import element_summary, parse_hierarchy


def _mk(serial: Optional[str]):
    adb = Adb(serial=serial)
    return adb, DeviceOps(adb), Actions(adb)


def run(serial: Optional[str] = None) -> None:
    from mcp.server.fastmcp import FastMCP  # optional dep

    mcp = FastMCP("droid-agent")

    @mcp.tool()
    def devices() -> str:
        """List attached Android devices (serial, state, model)."""
        adb, _, _ = _mk(serial)
        return json.dumps([d.__dict__ for d in adb.devices()])

    @mcp.tool()
    def dump_ui() -> str:
        """Dump the current screen as a numbered list of interactive
        elements (refs). Use the refs with tap/type/scroll calls."""
        adb, ops, _ = _mk(serial)
        elements = parse_hierarchy(ops.dump_ui_xml())
        session = sess.from_elements(adb.serial or "", elements)
        sess.save(session)
        return json.dumps([element_summary(el) for el in elements])

    @mcp.tool()
    def tap(ref: int) -> str:
        """Tap element #ref from the last dump_ui call."""
        adb, _, act = _mk(serial)
        el = sess.resolve_ref(sess.load(), ref)
        if not el:
            return json.dumps({"error": f"no element #{ref}; call dump_ui"})
        x, y = act.tap(ref, sess.load())
        return json.dumps({"tapped": ref, "x": x, "y": y, "label": el.get("label")})

    @mcp.tool()
    def tap_xy(x: int, y: int) -> str:
        """Tap raw coordinates."""
        _, _, act = _mk(serial)
        act.tap(f"{x},{y}")
        return json.dumps({"tapped": [x, y]})

    @mcp.tool()
    def type_text(text: str, clear: bool = False) -> str:
        """Type text into the focused field."""
        _, _, act = _mk(serial)
        act.type_text(text, clear=clear)
        return json.dumps({"typed": len(text)})

    @mcp.tool()
    def swipe(direction: str, distance: float = 0.6) -> str:
        """Swipe up/down/left/right (direction of content movement)."""
        adb, ops, act = _mk(serial)
        x1, y1, x2, y2 = act.swipe_dir(direction, ops.screen_size(), distance)
        return json.dumps({"from": [x1, y1], "to": [x2, y2]})

    @mcp.tool()
    def key(name: str) -> str:
        """Send a key event: back/home/enter/tab/del/power/..."""
        _, _, act = _mk(serial)
        return json.dumps({"key": name, "keyevent": act.key(name)})

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
    def device_state() -> str:
        """Foreground app, screen size/state, model, sdk."""
        _, ops, _ = _mk(serial)
        return json.dumps(ops.state().__dict__)

    @mcp.tool()
    def screenshot() -> str:
        """Current screen as base64 PNG."""
        _, ops, _ = _mk(serial)
        return base64.b64encode(ops.screenshot()).decode()

    @mcp.tool()
    def wait(seconds: float) -> str:
        """Sleep N seconds (let animations/loads settle)."""
        _, _, act = _mk(serial)
        act.wait(seconds)
        return json.dumps({"waited": seconds})

    mcp.run()
