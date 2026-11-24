"""High-level device operations: launch, stop, screenshot, state."""

from __future__ import annotations

import re
from dataclasses import dataclass

from droid_agent.actions import escape_input_text
from droid_agent.adb import Adb, AdbError
from droid_agent.events import emit

# package names are interpolated into `adb shell` strings — strict allowlist
_PKG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)*$")
_ACT_RE = re.compile(
    r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)*(/[a-zA-Z0-9_.$-]+)?$")


def _check_pkg(name: str) -> str:
    if not _PKG_RE.match(name or ""):
        raise AdbError(f"not a valid package name: {name!r}")
    return name


@dataclass
class DeviceState:
    foreground_package: str
    foreground_activity: str
    screen_on: bool
    screen_size: tuple[int, int]
    sdk: int
    model: str


class DeviceOps:
    def __init__(self, adb: Adb):
        self.adb = adb

    # -- apps ------------------------------------------------------------

    def launch(self, package: str, activity: str | None = None) -> str:
        _check_pkg(package)
        if activity:
            if not _ACT_RE.match(activity):
                raise AdbError(f"not a valid activity name: {activity!r}")
            comp = activity if "/" in activity else f"{package}/{activity}"
            out = self.adb.shell(f"am start -n {comp}").strip()
        else:
            out = self.adb.shell(
                f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
            ).strip()
            if "No activities found" in out:
                raise AdbError(
                    f"Package not installed or no launcher activity: {package}")
        emit("launch", package=package)
        return out

    def force_stop(self, package: str) -> str:
        out = self.adb.shell(f"am force-stop {_check_pkg(package)}").strip() or "ok"
        emit("stop", package=package)
        return out

    def clear(self, package: str) -> str:
        out = self.adb.shell(f"pm clear {_check_pkg(package)}").strip()
        emit("clear", package=package)
        return out

    def install(self, apk_path: str, reinstall: bool = False) -> str:
        # argv path, no shell interpolation — spaces are safe
        args = ["install"] + (["-r"] if reinstall else []) + [apk_path]
        out = self.adb.run(*args).strip()
        emit("install", apk=apk_path)
        return out

    def uninstall(self, package: str) -> str:
        out = self.adb.run("uninstall", _check_pkg(package)).strip()
        emit("uninstall", package=package)
        return out

    def is_installed(self, package: str) -> bool:
        out = self.adb.shell(f"pm list packages {_check_pkg(package)}")
        return f"package:{package}" in out

    # -- inspection --------------------------------------------------------

    def screen_size(self) -> tuple[int, int]:
        out = self.adb.shell("wm size")
        m = re.search(r"(\d+)x(\d+)", out)
        if not m:
            raise AdbError(f"Cannot parse screen size: {out!r}")
        return int(m.group(1)), int(m.group(2))

    def foreground(self) -> tuple[str, str]:
        """Return (package, activity) of the current foreground app."""
        out = self.adb.shell("dumpsys activity activities")
        m = re.search(
            r"(?:topResumedActivity|mResumedActivity|ResumedActivity)"
            r".*?(\S+)/(\S+)",
            out,
        )
        if not m:
            m = re.search(r"mCurrentFocus=\S+\s+\S+\s+(\S+)/(\S+?)}", out)
        if m:
            return m.group(1), m.group(2)
        return "", ""

    def screen_on(self) -> bool:
        out = self.adb.shell("dumpsys power")
        m = re.search(r"mWakefulness=(\w+)", out)
        return m.group(1) == "Awake" if m else True

    def state(self) -> DeviceState:
        pkg, act = self.foreground()
        sdk = self.adb.shell("getprop ro.build.version.sdk").strip()
        model = self.adb.shell("getprop ro.product.model").strip()
        return DeviceState(
            foreground_package=pkg,
            foreground_activity=act,
            screen_on=self.screen_on(),
            screen_size=self.screen_size(),
            sdk=int(sdk) if sdk.isdigit() else 0,
            model=model,
        )

    def unlock(self, pin: str | None = None) -> str:
        """Wake the screen and swipe the lockscreen away (best-effort).

        With `pin`, types it and presses Enter — covers PIN secure
        lockscreens. Pattern/fingerprint locks can't be typed past.
        """
        self.adb.shell("input keyevent 224")  # KEYCODE_WAKEUP
        w, h = self.screen_size()
        self.adb.shell(
            f"input swipe {w // 2} {int(h * 0.85)} {w // 2} {int(h * 0.15)} 200")
        if pin:
            self.adb.shell(f'input text "{escape_input_text(pin)}"')
            self.adb.shell("input keyevent 66")  # ENTER
        emit("unlock")
        return "ok"

    # -- media ------------------------------------------------------------

    def screenshot(self) -> bytes:
        """PNG bytes of the current screen (binary-safe via exec-out)."""
        png = self.adb.exec_out("screencap -p")
        if not png.startswith(b"\x89PNG"):
            raise AdbError("screencap did not return a PNG")
        emit("screenshot")
        return png

    def dump_ui_xml(self) -> str:
        """Raw uiautomator hierarchy XML (the agent's eyes)."""
        remote = "/sdcard/window_dump.xml"
        self.adb.shell(f"uiautomator dump {remote}")
        try:
            xml = self.adb.exec_out(f"cat {remote}").decode("utf-8", "replace")
        finally:
            self.adb.shell(f"rm -f {remote}")
        if "<hierarchy" not in xml:
            raise AdbError("uiautomator dump returned no hierarchy")
        return xml
