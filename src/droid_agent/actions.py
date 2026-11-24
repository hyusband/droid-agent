"""Touch / input actions resolved against the ref map."""

from __future__ import annotations

import re

from droid_agent.adb import Adb, AdbError
from droid_agent.events import emit
from droid_agent.session import Session, resolve_ref

# Android keyevent codes for the common keys agents need.
KEYCODES = {
    "back": 4, "home": 3, "recents": 187, "overview": 187,
    "enter": 66, "dpad_up": 19, "dpad_down": 20, "dpad_left": 21,
    "dpad_right": 22, "dpad_center": 23, "tab": 61, "space": 62,
    "del": 67, "delete": 67, "backspace": 67, "search": 84,
    "menu": 82, "power": 26, "wake": 224, "sleep": 223,
    "vol_up": 24, "vol_down": 25, "mute": 164,
    "camera": 27, "escape": 111,
}

_REF_RE = re.compile(r"^#?(\d+)$")
_XY_RE = re.compile(r"^(\d+)[,\s]+(\d+)$")


def parse_target(target: int | str) -> tuple[str, tuple[int, int]]:
    """'7' | '#7' | '540,1050' | '540 1050' -> ('ref'|'xy', payload)."""
    s = str(target).strip()
    m = _XY_RE.match(s)
    if m:
        return "xy", (int(m.group(1)), int(m.group(2)))
    m = _REF_RE.match(s)
    if m:
        return "ref", (int(m.group(1)), 0)
    raise AdbError(f"Cannot parse target: {target!r} (use a ref like 3 or x,y)")


def escape_input_text(text: str) -> str:
    """Escape a line for `adb shell input text "…"`.

    Inside the quoted arg only `"` `$` `\\` and backtick need escaping;
    spaces must become `%s`.
    """
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
        .replace(" ", "%s")
    )


def _resolve(session: Session | None, target: int | str,
             what: str) -> tuple[int, int, str]:
    kind, payload = parse_target(target)
    if kind == "xy":
        return payload[0], payload[1], f"{payload[0]},{payload[1]}"
    ref = payload[0]
    el = resolve_ref(session, ref)
    if not el or "center" not in el:
        raise AdbError(
            f"No element #{ref} in the current dump.\n"
            f"Run `droid-agent dump` first to refresh the ref map."
        )
    try:
        cx, cy = int(el["center"][0]), int(el["center"][1])
    except (TypeError, ValueError, IndexError, KeyError):
        raise AdbError(
            f"Element #{ref} has no usable coordinates — the stored dump "
            f"is corrupt. Run `droid-agent dump` again."
        )
    label = el.get("label") or el.get("kind") or f"#{ref}"
    _ = what  # kept for logging hooks
    return cx, cy, label


class Actions:
    def __init__(self, adb: Adb):
        self.adb = adb

    def tap(self, target: int | str, session: Session | None = None
            ) -> tuple[int, int]:
        x, y, label = _resolve(session, target, "tap")
        self.adb.shell(f"input tap {x} {y}")
        emit("tap", x=x, y=y, label=label)
        return x, y

    def long_press(self, target: int | str, duration_ms: int = 800,
                   session: Session | None = None) -> tuple[int, int]:
        x, y, label = _resolve(session, target, "long-press")
        self.adb.shell(f"input swipe {x} {y} {x} {y} {duration_ms}")
        emit("long_press", x=x, y=y, ms=duration_ms, label=label)
        return x, y

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 300) -> tuple[int, int, int, int]:
        self.adb.shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")
        emit("swipe", x1=x1, y1=y1, x2=x2, y2=y2, ms=duration_ms)
        return x1, y1, x2, y2

    def swipe_dir(self, direction: str, size: tuple[int, int],
                  distance: float = 0.6, duration_ms: int = 300
                  ) -> tuple[int, int, int, int]:
        w, h = size
        cx, cy = w // 2, h // 2
        dx, dy = int(w * distance / 2), int(h * distance / 2)
        start, end = {
            "up": ((cx, cy + dy), (cx, cy - dy)),
            "down": ((cx, cy - dy), (cx, cy + dy)),
            "left": ((cx + dx, cy), (cx - dx, cy)),
            "right": ((cx - dx, cy), (cx + dx, cy)),
        }.get(direction, (None, None))
        if not start or not end:
            raise AdbError(f"Unknown direction {direction!r} (up/down/left/right)")
        return self.swipe(start[0], start[1], end[0], end[1], duration_ms)

    def type_text(self, text: str, clear: bool = False) -> list[str]:
        """Type text; newlines become Enter keypresses.

        Returns a list of warnings (e.g. `%s` sequences the device will
        mangle — `input text` has no escape for it).
        """
        warnings: list[str] = []
        if "%s" in text or "%%" in text:
            warnings.append(
                "text contains '%s' — `input text` treats it as a space "
                "and cannot escape it; the device will receive a space")
        if clear:
            # no select-all keycombo over `input` — hammer backspace in one
            # shell call (50 chars max, covers typical fields)
            self.adb.shell("; ".join(["input keyevent 67"] * 50))
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if i:
                self.adb.shell("input keyevent 66")  # ENTER
            if not line:
                continue
            self.adb.shell(f'input text "{escape_input_text(line)}"')
        # never log the content — it may be a credential
        emit("type", chars=len(text))
        return warnings

    def key(self, name: str) -> int:
        code = KEYCODES.get(name.lower())
        if code is None:
            if name.isdigit():
                code = int(name)
                if code > 999:
                    raise AdbError(f"keyevent code out of range: {code}")
            else:
                raise AdbError(
                    f"Unknown key {name!r}. Known: {', '.join(sorted(KEYCODES))}"
                )
        self.adb.shell(f"input keyevent {code}")
        emit("key", name=name.lower(), code=code)
        return code

    def wait(self, seconds: float) -> None:
        import time

        time.sleep(max(0.0, seconds))
