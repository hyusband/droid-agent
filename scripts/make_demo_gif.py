"""Regenerate assets/demo.gif — the README terminal demo.

Split-screen: styled terminal (left) + REAL POCO F5 screen capture (right).
Sensitive fields in the raw captures (Wi-Fi SSID, device owner name) are
masked at render time; raw PNGs stay gitignored under assets/src/.
"""

import os

from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1280, 720
FPS_MS = 55

# -- contemporary tokens --------------------------------------------------
BG_TOP = "#0e0a14"
BG_BOT = "#1a0f26"
CARD = "#0d1117"
CARD_BAR = "#151a23"
CARD_EDGE = "#2b2340"
FG = "#e6edf3"
DIM = "#8b949e"
FAINT = "#565d67"
PINK = "#E60076"
PURPLE = "#C800DF"
BLUE = "#79c0ff"
GREEN = "#3fb950"

SRC = os.path.join(os.path.dirname(__file__), "..", "assets", "src")
OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "demo.gif")

MONO = ImageFont.truetype("CascadiaCode.ttf", 17)
MONO_B = ImageFont.truetype("CascadiaCode.ttf", 17)
TITLE = ImageFont.truetype("CascadiaCode.ttf", 15)
KICKER = ImageFont.truetype("CascadiaCode.ttf", 15)
PHONE_FONT = ImageFont.truetype("CascadiaCode.ttf", 15)

TERM = dict(x=42, y=82, w=760, h=592)
PHONE = dict(x=848, y=52, w=388, h=640)
BEZEL = 12

# -- terminal script -------------------------------------------------------
LINES = []  # rendered line list: (kind, text)


def beat_devices():
    yield ("cmd", "droid-agent devices")
    yield ("out_dim", "diy9ljdyhiwgqglb      device    POCO F5 · Android 16")


def beat_dump_settings():
    yield ("cmd", "droid-agent dump")
    rows = [
        ("[ 1]", "input ", "Search settings", "( 540, 497)"),
        ("[ 2]", "list  ", "recyclerview", "( 540,1487)"),
        ("[ 3]", "button", "About phone", "( 540, 663)"),
        ("[ 4]", "button", "System apps updater", "( 540, 817)"),
        ("[ 5]", "button", "Security status", "( 540, 971)"),
        ("[ 6]", "button", "Wi-Fi", "( 540,1159)"),
        ("[ 7]", "button", "Bluetooth", "( 540,1313)"),
        ("[ 8]", "button", "Mobile networks", "( 540,1467)"),
    ]
    for ref, kind, label, xy in rows:
        yield ("el", ref, kind, label, xy)
    yield ("out_dim", "12 elements · tap with `droid-agent tap <ref>`")


def beat_tap():
    yield ("cmd", "droid-agent tap 3")
    yield ("out_ok", "tapped (540, 663)  →  About phone")


def beat_dump_about():
    yield ("cmd", "droid-agent dump")
    rows = [
        ("[ 1]", "scroll", "scrollview", "( 540,1332)"),
        ("[ 2]", "button", "Device name", "( 540,1407)"),
        ("[ 3]", "button", "Storage", "( 540,1548)"),
        ("[ 4]", "button", "OS version (for POCO)", "( 540,1750)"),
        ("[ 5]", "text  ", "Android version", "( 242,1957)"),
        ("[ 6]", "text  ", "16 BP2A.250605.031.A3", "( 790,1957)"),
    ]
    for ref, kind, label, xy in rows:
        yield ("el", ref, kind, label, xy)
    yield ("out_ok", "6 elements · verified: About phone opened")


SCRIPT = [
    (beat_devices, "settings", None, 26),
    (beat_dump_settings, "settings", None, 34),
    (beat_tap, "settings", (540, 663), 26),
    (beat_dump_about, "about", None, 95),
]


# -- drawing helpers ---------------------------------------------------------

def _vgrad(w, h, top, bot):
    base = Image.new("RGB", (1, h))
    tr, tg, tb = [int(top[i:i + 2], 16) for i in (1, 3, 5)]
    br, bg_, bb = [int(bot[i:i + 2], 16) for i in (1, 3, 5)]
    for y in range(h):
        t = y / max(1, h - 1)
        base.putpixel((0, y), (
            int(tr + (br - tr) * t), int(tg + (bg_ - tg) * t),
            int(tb + (bb - tb) * t)))
    return base.resize((w, h))


def _rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1],
                                        radius=radius, fill=255)
    return m


_PHONE_CACHE = {}


def _masked_screen(name):
    """Real capture with personal fields covered."""
    if name in _PHONE_CACHE:
        return _PHONE_CACHE[name]
    img = Image.open(os.path.join(SRC, f"{name}.png")).convert("RGB")
    d = ImageDraw.Draw(img)
    def cover(x0, y0, x1, y1, repl=None, tx=None, ty=None):
        # sample card background a few px left of the field
        bg = img.getpixel((x0 - 260, (y0 + y1) // 2))
        d.rectangle([x0, y0, x1, y1], fill=bg)
        if repl:
            d.text((tx if tx is not None else x0 + 4,
                    ty if ty is not None else y0 + ((y1 - y0) // 2) - 12),
                   repl, font=PHONE_FONT, fill="#8a8a8e")
    if name == "settings":
        cover(520, 1100, 1030, 1200, "Home Wi-Fi", tx=700, ty=1135)
    elif name == "about":
        cover(640, 1375, 1030, 1455, "POCO F5", tx=780, ty=1392)
    _PHONE_CACHE[name] = img
    return img


def _phone_panel(screen_name, ripple=None):
    """Bezel + real screenshot, optional tap ripple at device coords."""
    bezel_w, bezel_h = PHONE["w"], PHONE["h"]
    panel = Image.new("RGBA", (bezel_w, bezel_h), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle([0, 0, bezel_w - 1, bezel_h - 1], radius=44,
                         fill="#141416")
    inner = [BEZEL, BEZEL, bezel_w - BEZEL, bezel_h - BEZEL]
    scr = _masked_screen(screen_name)
    sw, sh = inner[2] - inner[0], inner[3] - inner[1]
    scr = scr.resize((sw, sh), Image.LANCZOS)
    mask = _rounded_mask((sw, sh), 34)
    panel.paste(scr, (inner[0], inner[1]), mask)
    # camera dot
    pd.ellipse([bezel_w // 2 - 5, BEZEL + 8, bezel_w // 2 + 5, BEZEL + 18],
               fill="#000")
    if ripple:
        cx, cy, t = ripple  # device px + progress 0..1
        px = inner[0] + cx * sw / 1080
        py = inner[1] + cy * sh / 2400
        for r_frac, alpha in ((0.55, 200), (0.8, 140), (1.0, 90)):
            r = 8 + t * 60 * r_frac
            a = int(alpha * (1 - t))
            pd.ellipse([px - r, py - r, px + r, py + r],
                       outline=(*[int(PINK[i:i + 2], 16) for i in (1, 3, 5)], a),
                       width=4)
        pd.ellipse([px - 6, py - 6, px + 6, py + 6],
                   fill=tuple(int(PINK[i:i + 2], 16) for i in (1, 3, 5)))
    return panel


def _draw_terminal(d, lines, typed=None, cursor_on=True):
    x, y, w, h = TERM["x"], TERM["y"], TERM["w"], TERM["h"]
    d.rounded_rectangle([x, y, x + w, y + h], radius=18, fill=CARD,
                        outline=CARD_EDGE, width=1)
    d.rounded_rectangle([x, y, x + w, y + 40], radius=18, fill=CARD_BAR)
    d.rectangle([x, y + 22, x + w, y + 40], fill=CARD_BAR)
    for i, c in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        d.ellipse([x + 18 + i * 22, y + 13, x + 32 + i * 22, y + 27], fill=c)
    d.text((x + w // 2 - 105, y + 10), "droid-agent — live · POCO F5",
           font=TITLE, fill=DIM)
    ty = y + 56
    max_y = y + h - 14
    shown = list(lines)
    if typed is not None:
        shown.append(("typed", typed))
    for row in shown[-(int((h - 66) // 24)):]:
        if ty > max_y:
            break
        kind = row[0]
        if kind in ("cmd", "typed"):
            text = row[1]
            d.text((x + 16, ty), "❯", font=MONO, fill=PINK)
            d.text((x + 40, ty), text, font=MONO, fill=FG)
            ty += 24
        elif kind == "out_dim":
            d.text((x + 40, ty), row[1], font=MONO, fill=DIM)
            ty += 24
        elif kind == "out_ok":
            d.text((x + 40, ty), row[1], font=MONO, fill=GREEN)
            ty += 24
        elif kind == "el":
            ref, ekind, label, xy = row[1:]
            hot = label in ("About phone", "Android version",
                            "16 BP2A.250605.031.A3")
            d.text((x + 40, ty), ref, font=MONO,
                   fill=PURPLE if hot else BLUE)
            d.text((x + 96, ty), f"{ekind:<8}", font=MONO,
                   fill=PINK if hot else FAINT)
            d.text((x + 190, ty), label, font=MONO,
                   fill=FG if hot else DIM)
            d.text((x + 560, ty), xy, font=MONO, fill=FAINT)
            ty += 24
    if cursor_on:
        cy = ty
        if shown and shown[-1][0] in ("cmd", "typed"):
            pass
        d.rectangle([x + 40, cy, x + 51, cy + 18], fill=FG)


def frame(lines, phone, typed=None, ripple=None, cursor_on=True):
    img = _vgrad(W, H, BG_TOP, BG_BOT).convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    kick = "agent-native android control"
    d.text((TERM["x"] + 4, 46), kick, font=KICKER, fill=DIM)
    d.text((TERM["x"] + 4 + KICKER.getlength(kick) + 8, 46),
           "— stock adb, zero device install", font=KICKER, fill=PINK)
    _draw_terminal(d, lines, typed, cursor_on)
    img.alpha_composite(_phone_panel(phone, ripple),
                        (PHONE["x"], PHONE["y"]))
    return img.convert("RGB")


def main():
    frames = []

    def emit(img, n=1):
        for _ in range(n):
            frames.append(img)

    lines = []
    emit(frame(lines, "settings"), 18)  # settle on empty term + phone
    blink = 0
    for beat_fn, phone, tap_pt, hold in SCRIPT:
        for ev in beat_fn():
            if ev[0] == "cmd":
                typed = ""
                for ch in ev[1]:
                    typed += ch
                    emit(frame(lines, phone, typed), 1)
                lines.append(("cmd", ev[1]))
                emit(frame(lines, phone), 4)
            else:
                lines.append(ev)
                emit(frame(lines, phone), 2)
        emit(frame(lines, phone), hold)
        if tap_pt:
            cx, cy = tap_pt
            for t in (0.15, 0.35, 0.55, 0.8, 1.0):
                emit(frame(lines, "about" if t > 0.55 else phone,
                           ripple=(cx, cy, t)), 4)
    # loop-close blink
    for _ in range(10):
        emit(frame(lines, "about", cursor_on=(blink := not blink)))

    frames[0].save(OUT, save_all=True, append_images=frames[1:],
                   duration=FPS_MS, loop=0, optimize=True)
    print(f"{OUT}  {len(frames)} frames")


if __name__ == "__main__":
    main()
