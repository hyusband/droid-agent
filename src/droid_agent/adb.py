"""Thin wrapper around the ``adb`` binary.

Zero dependencies: locates the platform-tools adb executable and provides
text/binary command execution plus device listing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass


class AdbError(RuntimeError):
    """Raised when an adb command fails or adb cannot be located."""


ADB_NOT_FOUND = (
    "adb executable not found.\n"
    "Install Android platform-tools and make sure 'adb' is on your PATH:\n"
    "  https://developer.android.com/tools/releases/platform-tools\n"
    "Or set ANDROID_HOME / ANDROID_SDK_ROOT to your SDK directory."
)


def find_adb(explicit: str | None = None) -> str:
    """Locate the adb binary: explicit path -> PATH -> SDK env vars."""
    candidates: list[str] = []
    if explicit:
        if not os.path.isfile(explicit):
            raise AdbError(f"--adb path does not exist: {explicit}")
        return explicit
    which = shutil.which("adb")
    if which:
        candidates.append(which)
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        root = os.environ.get(env)
        if root:
            exe = "adb.exe" if sys.platform == "win32" else "adb"
            candidates.append(os.path.join(root, "platform-tools", exe))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    if which:
        return which
    raise AdbError(ADB_NOT_FOUND)


@dataclass
class Device:
    serial: str
    state: str  # device / unauthorized / offline / no permissions
    model: str = ""
    product: str = ""
    transport_id: str = ""


class Adb:
    """Command runner bound to one adb binary and (optionally) one device."""

    def __init__(self, serial: str | None = None, adb_path: str | None = None,
                 timeout: float = 30.0):
        self.serial = serial
        self.adb_path = find_adb(adb_path)
        self.timeout = timeout

    def _base(self) -> list[str]:
        args = [self.adb_path]
        if self.serial:
            args += ["-s", self.serial]
        return args

    def run(self, *args: str, timeout: float | None = None) -> str:
        """Run an adb command, return stdout as text. Raise AdbError on failure."""
        try:
            proc = subprocess.run(
                self._base() + list(args),
                capture_output=True,
                timeout=timeout or self.timeout,
            )
        except subprocess.TimeoutExpired:
            raise AdbError(
                f"adb {' '.join(args)} timed out — device unresponsive?")
        except (FileNotFoundError, OSError) as e:
            raise AdbError(f"cannot run adb at {self.adb_path!r}: {e}")
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        stdout = proc.stdout.decode("utf-8", "replace")
        if proc.returncode != 0:
            raise AdbError(
                f"adb {' '.join(args)} failed ({proc.returncode}): "
                f"{stderr or stdout.strip()}"
            )
        # adb occasionally reports errors on stdout/stderr with rc=0
        for channel in (stdout, stderr):
            if channel.lstrip().lower().startswith("error:"):
                raise AdbError(channel.strip())
        return stdout

    def shell(self, cmd: str, timeout: float | None = None) -> str:
        return self.run("shell", cmd, timeout=timeout)

    def exec_out(self, cmd: str, timeout: float | None = None) -> bytes:
        """Binary-safe exec-out (screenshots, file reads)."""
        proc = subprocess.run(
            self._base() + ["exec-out", cmd],
            capture_output=True,
            timeout=timeout or self.timeout,
        )
        if proc.returncode != 0:
            raise AdbError(
                f"adb exec-out failed ({proc.returncode}): "
                f"{proc.stderr.decode('utf-8', 'replace').strip()}"
            )
        return proc.stdout

    def push(self, local: str, remote: str) -> str:
        return self.run("push", local, remote)

    def pull(self, remote: str, local: str) -> str:
        return self.run("pull", remote, local)

    # -- connectivity ----------------------------------------------------

    def connect(self, host: str, port: int = 5555) -> str:
        return self.run("connect", f"{host}:{port}").strip()

    def pair(self, host: str, port: int, code: str) -> str:
        """Android 11+ wireless pairing."""
        return self.run("pair", f"{host}:{port}", code).strip()

    def disconnect(self, host: str | None = None,
                   port: int | None = None) -> str:
        if host and port:
            target = f"{host}:{port}"
        elif host:
            target = host
        else:
            target = ""
        return self.run("disconnect", *([target] if target else [])).strip()

    # -- listing -----------------------------------------------------------

    def devices(self) -> list[Device]:
        out = self.run("devices", "-l")
        result: list[Device] = []
        attr_prefixes = ("model:", "device:", "product:",
                         "transport_id:", "usb:")
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            # state = tokens until the first key:value attribute
            # (handles multi-word states like "no permissions (...)")
            state_parts = []
            idx = 1
            while idx < len(parts) and not parts[idx].startswith(attr_prefixes):
                state_parts.append(parts[idx])
                idx += 1
            dev = Device(serial=parts[0], state=" ".join(state_parts) or "?")
            for kv in parts[idx:]:
                if kv.startswith("model:"):
                    dev.model = kv.split(":", 1)[1]
                elif kv.startswith("product:"):
                    dev.product = kv.split(":", 1)[1]
                elif kv.startswith("transport_id:"):
                    dev.transport_id = kv.split(":", 1)[1]
            result.append(dev)
        return result

    def require_device(self) -> None:
        """Fail fast if no device is reachable; auto-select a single device."""
        devs = [d for d in self.devices() if d.state == "device"]
        if not devs:
            raise AdbError(
                "No device attached.\n"
                "  - USB: plug in a device with USB debugging enabled\n"
                "  - WiFi: droid-agent connect <ip>:5555\n"
                "  - Emulator: start one, it shows up automatically"
            )
        if self.serial:
            if not any(d.serial == self.serial for d in devs):
                raise AdbError(
                    f"Device '{self.serial}' not found. Attached: "
                    + ", ".join(d.serial for d in devs)
                )
        elif len(devs) == 1:
            self.serial = devs[0].serial
        else:
            raise AdbError(
                "Multiple devices attached — pick one with -s:\n"
                + "\n".join(f"  {d.serial}  ({d.model or 'device'})"
                            for d in devs)
            )
