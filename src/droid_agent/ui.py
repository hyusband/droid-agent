"""uiautomator hierarchy -> numbered interactive elements.

This is the core value of droid-agent: instead of dumping a raw 500-line
XML tree at an LLM, we distill it into a short list of *actionable*
elements with stable refs, the same way browser-use does for the DOM.

    [1] input    "Clave de acceso"            (540, 640)
    [2] button   "ACTIVAR"                    (540, 1050)
    [3] scroll   RecyclerView                 (540, 1400)
    [4] text     "Clave expirada."            (540, 380)
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

# class short-name -> element kind
_KIND_MAP = [
    ("edittext", "input"),
    ("button", "button"),
    ("imagebutton", "button"),
    ("checkbox", "checkbox"),
    ("switch", "switch"),
    ("radiobutton", "radio"),
    ("seekbar", "slider"),
    ("spinner", "dropdown"),
    ("recyclerview", "list"),
    ("listview", "list"),
    ("scrollview", "scroll"),
    ("viewpager", "pager"),
    ("webview", "webview"),
]


@dataclass
class Element:
    ref: int
    kind: str
    text: str
    desc: str
    label: str
    resource_id: str
    class_name: str
    bounds: tuple[int, int, int, int]
    cx: int
    cy: int
    clickable: bool
    editable: bool
    scrollable: bool
    long_clickable: bool
    checkable: bool
    checked: bool
    enabled: bool
    focused: bool
    password: bool
    selected: bool
    depth: int
    children: list[Element] = field(default_factory=list)


def _parse_bounds(raw: str) -> tuple[int, int, int, int]:
    m = _BOUNDS_RE.match(raw or "")
    if not m:
        return (0, 0, 0, 0)
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))


def _truthy(raw: str | None) -> bool:
    return raw == "true"


def _class_short(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if name else ""


def classify(class_name: str, clickable: bool, editable: bool,
             scrollable: bool) -> str:
    short = _class_short(class_name)
    for token, kind in _KIND_MAP:
        if token in short:
            return kind
    if editable:
        return "input"
    if scrollable:
        return "scroll"
    if clickable:
        return "button"
    return "text"


def _collect_label(el: ET.Element) -> tuple[str, str]:
    """Best label: own text/desc, else nearest descendant's.

    Skips password-marked descendants — their text is a credential and
    must never be harvested into a parent's label."""
    text = el.get("text", "").strip()
    desc = el.get("content-desc", "").strip()
    if text or desc:
        return text, desc
    for child in el:
        if _truthy(child.get("password")):
            continue
        ct = child.get("text", "").strip()
        cd = child.get("content-desc", "").strip()
        if ct or cd:
            return ct, cd
    for node in el.iter():
        if node is el or _truthy(node.get("password")):
            continue
        ct = node.get("text", "").strip()
        cd = node.get("content-desc", "").strip()
        if ct or cd:
            return ct, cd
    return "", ""


def _is_interesting(el: ET.Element) -> bool:
    if _truthy(el.get("clickable")) or _truthy(el.get("long-clickable")):
        return True
    if _truthy(el.get("scrollable")) or _truthy(el.get("checkable")):
        return True
    if "edittext" in _class_short(el.get("class", "")):
        return True
    if el.get("text", "").strip() or el.get("content-desc", "").strip():
        return True
    return False


# Invisible format chars a malicious app can use to smuggle prompt-injection
# text into element labels/descriptions: zero-width spaces & joiners, bidi
# overrides/isolates (what you see != what the model reads), soft hyphen,
# BOM, tag/variation chars. The screen looks clean; the agent reads an order.
_INVISIBLE_RE = re.compile(
    "[\u00ad\u034f\u061c\u115f-\u1160\u17b4-\u17b5\u180e\u200b-\u200f"
    "\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufe00-\ufe0f\ufeff"
    "\ufff9-\ufffb\U0001bca0-\U0001bca3\U0001d173-\U0001d17a"
    "\U000e0000-\U000e0fff]"
)
# C0/C1 minus whitespace (\x09-\x0d are collapsed to a space by split())
_C0C1_RE = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]")


def _sanitize(text: str) -> str:
    """Strip invisible/format and control chars, collapse whitespace."""
    cleaned = _INVISIBLE_RE.sub("", text)
    cleaned = _C0C1_RE.sub("", " ".join(cleaned.split()))
    return unicodedata.normalize("NFC", cleaned)


def _clean(text: str, cap: int = 200) -> str:
    """Sanitize + bound length (newlines break the table)."""
    cleaned = _sanitize(text)
    return cleaned[:cap - 3] + "..." if len(cleaned) > cap else cleaned


def _build(el: ET.Element, depth: int, ref_counter: list[int],
           ancestor_clickable: bool) -> Element | None:
    b = _parse_bounds(el.get("bounds", ""))
    clickable = _truthy(el.get("clickable"))
    editable = _class_short(el.get("class", "")) == "edittext"
    scrollable = _truthy(el.get("scrollable"))

    # skip decorative children of a clickable parent (the parent is the ref),
    # and degenerate elements (offscreen slivers — tapping center is useless)
    w, h = b[2] - b[0], b[3] - b[1]
    keep = _is_interesting(el) and not ancestor_clickable \
        and w >= 8 and h >= 8

    node: Element | None = None
    if keep:
        ref_counter[0] += 1
        # only pull descendant labels for tappables — a scroll container's
        # label should not be its first child's text
        text, desc = _collect_label(el) if clickable else (
            el.get("text", "").strip(), el.get("content-desc", "").strip())
        own_text = _sanitize(el.get("text", ""))
        own_desc = _sanitize(el.get("content-desc", ""))
        is_password = _truthy(el.get("password"))
        if is_password:
            # never leak credentials into dumps / session.json / --json
            text = desc = own_text = own_desc = ""
        label = _clean(
            own_text or own_desc or text or desc
            or _class_short(el.get("class", "")))
        if is_password:
            label = "••••"
        node = Element(
            ref=ref_counter[0],
            kind=classify(el.get("class", ""), clickable, editable, scrollable),
            text=_sanitize(own_text or text),
            desc=_sanitize(own_desc or desc),
            label=label,
            resource_id=el.get("resource-id", ""),
            class_name=el.get("class", ""),
            bounds=b,
            cx=(b[0] + b[2]) // 2,
            cy=(b[1] + b[3]) // 2,
            clickable=clickable,
            editable=editable,
            scrollable=scrollable,
            long_clickable=_truthy(el.get("long-clickable")),
            checkable=_truthy(el.get("checkable")),
            checked=_truthy(el.get("checked")),
            enabled=el.get("enabled", "true") != "false",
            focused=_truthy(el.get("focused")),
            password=is_password,
            selected=_truthy(el.get("selected")),
            depth=depth,
        )

    kids: list[Element] = []
    for child in el:
        child_el = _build(child, depth + 1, ref_counter,
                          ancestor_clickable or clickable)
        if child_el:
            kids.append(child_el)

    if node:
        node.children = kids
        return node
    if kids:
        # transparent container: hoist children up
        return _Container(kids)  # type: ignore[return-value]
    return None


class _Container(Element):
    """Invisible layout node: carries children but no ref."""

    def __init__(self, kids: list[Element]):
        super().__init__(
            ref=0, kind="container", text="", desc="", label="",
            resource_id="", class_name="", bounds=(0, 0, 0, 0),
            cx=0, cy=0, clickable=False, editable=False, scrollable=False,
            long_clickable=False, checkable=False, checked=False,
            enabled=True, focused=False, password=False, selected=False,
            depth=0, children=kids,
        )


def parse_hierarchy(xml: str) -> list[Element]:
    """Parse uiautomator XML into the flat ref list (containers hoisted)."""
    start = xml.find("<hierarchy")
    if start < 0:
        raise ValueError("no <hierarchy> in dump")
    try:
        root = ET.fromstring(xml[start:])
    except ET.ParseError as e:
        raise ValueError(f"malformed hierarchy XML: {e}")
    try:
        refs = [0]
        top: list[Element] = []
        for child in root:
            el = _build(child, 0, refs, False)
            if not el:
                continue
            if isinstance(el, _Container):
                top.extend(el.children)
            else:
                top.append(el)
        return _flatten(top)
    except RecursionError:
        raise ValueError("hierarchy too deep to parse (>~1000 levels)")


def _flatten(els: list[Element]) -> list[Element]:
    out: list[Element] = []

    def walk(nodes: list[Element]):
        for n in nodes:
            if isinstance(n, _Container):
                walk(n.children)
                continue
            out.append(n)
            if n.children:
                walk(n.children)

    walk(els)
    return out


def element_summary(el: Element) -> dict:
    return {
        "ref": el.ref,
        "kind": el.kind,
        "label": el.label,
        "text": el.text,
        "desc": el.desc,
        "id": el.resource_id,
        "center": [el.cx, el.cy],
        "bounds": list(el.bounds),
        "clickable": el.clickable,
        "editable": el.editable,
        "scrollable": el.scrollable,
        "enabled": el.enabled,
        "checked": el.checked,
        "password": el.password,
    }


def extract_text(xml: str, cap: int = 100) -> list[dict]:
    """Every visible text/desc on screen — for agents that read, not tap.

    dump_ui filters to *actionable* elements; this walks the raw XML and
    collects every non-empty text/content-desc (sanitized, passwords
    skipped, capped) so an agent can read a screen without acting on it.
    """
    start = xml.find("<hierarchy")
    if start < 0:
        raise ValueError("no <hierarchy> in dump")
    try:
        root = ET.fromstring(xml[start:])
    except ET.ParseError as e:
        raise ValueError(f"malformed hierarchy XML: {e}")
    out: list[dict] = []
    for node in root.iter("node"):
        if _truthy(node.get("password")):
            continue
        text = _clean(node.get("text", ""))
        desc = _clean(node.get("content-desc", ""))
        if not text and not desc:
            continue
        out.append({
            "text": text,
            "desc": desc,
            "class": _class_short(node.get("class", "")),
            "bounds": list(_parse_bounds(node.get("bounds", ""))),
        })
        if len(out) >= cap:
            break
    return out


def find_by_ref(elements: list[Element], ref: int) -> Element | None:
    for el in elements:
        if el.ref == ref:
            return el
    return None


def find_elements(
    elements: list[Element],
    text: str | None = None,
    kind: str | None = None,
    clickable: bool | None = None,
    editable: bool | None = None,
    exact: bool = False,
) -> list[Element]:
    """Filter the flat ref list — substring (or exact) match on
    label/text/desc plus optional kind/clickable/editable filters.

    Lets agents query the UI tree ("the button that says 'Allow'")
    without parsing a full dump, which is the dominant workflow.
    """
    needle = _sanitize(text).lower() if text else None

    def matches_text(el: Element) -> bool:
        if needle is None:
            return True
        fields = (el.label, el.text, el.desc)
        if exact:
            return any(f.lower() == needle for f in fields if f)
        return any(needle in f.lower() for f in fields if f)

    return [
        el
        for el in elements
        if matches_text(el)
        and (kind is None or el.kind == kind)
        and (clickable is None or el.clickable == clickable)
        and (editable is None or el.editable == editable)
    ]
