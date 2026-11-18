import os

from droid_agent.ui import find_by_ref, parse_hierarchy

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "login_dump.xml")


def _elements():
    with open(FIXTURE, encoding="utf-8") as fh:
        return parse_hierarchy(fh.read())


def test_parse_counts_only_interesting():
    els = _elements()
    # title, error text, key field, pw field, activate btn (child text hoisted
    # into it, NOT its own ref), help btn, recyclerview, 2 list items, nav img
    assert len(els) == 10
    assert [e.ref for e in els] == list(range(1, 11))


def test_clickable_parent_absorbs_child_text():
    els = _elements()
    btn = find_by_ref(els, 5)
    assert btn is not None
    assert btn.kind == "button"
    assert btn.label == "ACTIVAR"  # pulled up from the child TextView
    # the child TextView must NOT have its own ref
    assert not any(e.label == "ACTIVAR" and e is not btn for e in els)


def test_edittext_is_input():
    els = _elements()
    key_field = find_by_ref(els, 3)
    assert key_field.kind == "input"
    assert key_field.editable
    assert key_field.desc == "Clave de acceso"


def test_password_flagged():
    els = _elements()
    pw = find_by_ref(els, 4)
    assert pw.password
    assert pw.kind == "input"


def test_disabled_button_kept_but_marked():
    els = _elements()
    help_btn = find_by_ref(els, 6)
    assert help_btn.label == "Ayuda"
    assert help_btn.enabled is False


def test_scroll_container_and_children():
    els = _elements()
    rv = find_by_ref(els, 7)
    assert rv.kind == "list"
    assert rv.scrollable
    assert rv.children and len(rv.children) == 2
    item = find_by_ref(els, 8)
    assert item.label == "Opcion uno"
    assert item.kind == "button"  # clickable TextView = tappable target
    assert item.clickable


def test_image_button_with_desc():
    els = _elements()
    nav = find_by_ref(els, 10)
    assert nav.kind == "button"
    assert nav.label == "navigate up"


def test_centers_computed():
    els = _elements()
    btn = find_by_ref(els, 5)
    assert (btn.cx, btn.cy) == (540, 1050)
