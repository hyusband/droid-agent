"""Rendering: human-readable tables and agent-friendly JSON."""

from __future__ import annotations

import json
import sys
from typing import Any, List

from droid_agent.ui import Element

_KIND_GLYPH = {
    "input": ">>", "button": "()", "checkbox": "[x]", "switch": "~/~",
    "radio": "(o)", "slider": "-o-", "dropdown": "vv", "list": "|||",
    "scroll": "|v|", "pager": "<>", "webview": "www", "text": " T ",
}


def emit(payload: Any, as_json: bool) -> None:
    if as_json:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")


def render_elements(elements: List[Element]) -> str:
    lines = []
    for el in elements:
        glyph = _KIND_GLYPH.get(el.kind, " ? ")
        label = el.label if len(el.label) <= 46 else el.label[:43] + "..."
        state = ""
        if not el.enabled:
            state += " [disabled]"
        if el.checked:
            state += " [checked]"
        if el.password:
            label = "•" * max(4, len(el.label) or 8)
        rid = el.resource_id.rsplit("/", 1)[-1] if el.resource_id else ""
        rid_str = f"  · {rid}" if rid and not label else f"  ({rid})" if rid else ""
        lines.append(
            f"[{el.ref:>2}] {glyph:<5} {label:<48} ({el.cx:>4},{el.cy:>4}){rid_str}{state}"
        )
    return "\n".join(lines)
