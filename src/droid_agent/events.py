"""Agent-action event log — the feed behind `droid-agent watch`.

Every semantic action (tap, swipe, type, key, shell, unlock, narrate)
appends one JSON line to ``~/.droid-agent/events.jsonl``. The watcher
tails it over SSE so a human can see, live, what the agent is doing —
the "agent hands" half of the viewer.

Privacy: typed text is logged as a char count + target label only —
never the content itself (it may be a credential).
"""

from __future__ import annotations

import json
import os
import time

_MAX_BYTES = 1_000_000
_KEEP_LINES = 400


def _events_path() -> str:
    base = os.environ.get("DROID_AGENT_HOME") or os.path.join(
        os.path.expanduser("~"), ".droid-agent"
    )
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "events.jsonl")


def emit(kind: str, **data) -> None:
    """Append one event; never raises — watching must never break acting."""
    try:
        path = _events_path()
        rec = {"t": round(time.time(), 3), "kind": kind, **data}
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if os.path.getsize(path) > _MAX_BYTES:
            _rotate(path)
    except OSError:
        pass


def _rotate(path: str) -> None:
    """Keep the tail — the log is a live feed, not an archive."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()[-_KEEP_LINES:]
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        os.replace(tmp, path)
    except OSError:
        try:
            os.truncate(path, 0)
        except OSError:
            pass


def tail(path: str | None = None):
    """Generator: yields (offset, record-json-str) for new lines."""
    path = path or _events_path()
    pos = os.path.getsize(path) if os.path.isfile(path) else 0
    while True:
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        if size < pos:  # rotated under us
            pos = 0
        if size > pos:
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    fh.seek(pos)
                    chunk = fh.read()
                    pos = fh.tell()
            except OSError:
                chunk = ""
            for line in chunk.splitlines():
                if line.strip():
                    yield pos, line
        else:
            yield pos, None


def recent(n: int = 20, path: str | None = None) -> list[str]:
    """Last n raw JSON lines — SSE replay on connect."""
    path = path or _events_path()
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return [ln for ln in fh.readlines()[-n:] if ln.strip()]
    except OSError:
        return []


def clear() -> None:
    path = _events_path()
    if os.path.isfile(path):
        os.remove(path)
