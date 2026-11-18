"""Ref-map persistence.

``droid-agent dump`` numbers elements 1..N. Those numbers only exist in
our head — so we persist the last dump per device at
``~/.droid-agent/session.json`` and resolve ``tap 3`` against it.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from droid_agent.ui import Element, element_summary

STALE_SECONDS = 120.0


def _session_path() -> str:
    base = os.environ.get("DROID_AGENT_HOME") or os.path.join(
        os.path.expanduser("~"), ".droid-agent"
    )
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "session.json")


@dataclass
class Session:
    device: str = ""
    dumped_at: float = 0.0
    elements: List[dict] = field(default_factory=list)

    @property
    def stale_seconds(self) -> float:
        return time.time() - self.dumped_at if self.dumped_at else float("inf")

    @property
    def is_stale(self) -> bool:
        return self.stale_seconds > STALE_SECONDS


def save(session: Session) -> None:
    path = _session_path()
    # unique tmp name per writer — concurrent dumps must not share a file
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(
            {"device": session.device, "dumped_at": session.dumped_at,
             "elements": session.elements},
            fh,
        )
    try:
        os.replace(tmp, path)
    except OSError:
        # Windows: a racing reader can hold the file — retry once, else drop
        try:
            os.replace(tmp, path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass


def load() -> Optional[Session]:
    path = _session_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            return None
        elements = raw.get("elements")
        if not isinstance(elements, list):
            elements = []
        elements = [e for e in elements if isinstance(e, dict)]
        return Session(
            device=str(raw.get("device") or ""),
            dumped_at=float(raw.get("dumped_at") or 0.0),
            elements=elements,
        )
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        return None


def from_elements(device: str, elements: List[Element]) -> Session:
    return Session(
        device=device,
        dumped_at=time.time(),
        elements=[element_summary(el) for el in elements],
    )


def resolve_ref(session: Optional[Session], ref: int) -> Optional[dict]:
    if not session:
        return None
    for el in session.elements:
        if el.get("ref") == ref:
            return el
    return None


def clear() -> None:
    path = _session_path()
    if os.path.isfile(path):
        os.remove(path)
