"""Live device mirror — watch the agent drive the phone, in a browser.

`droid-agent watch` serves a localhost page with:

  * the screen, live — h264 from the device's own hardware encoder
    (stock ``screenrecord``, nothing installed on-device) decoded in the
    browser by jmuxer/MSE at ~30fps; MJPEG screencap polling (~2fps) as
    automatic fallback on devices where screenrecord misbehaves
  * every agent action drawn on top — tap ripples, swipe arrows, a live
    action ticker, and `narrate` callouts — fed by the events.jsonl the
    Actions/DeviceOps layers append to (CLI and MCP both flow through it)

Zero deps: stdlib http.server + SSE; jmuxer.js is a vendored static asset.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from droid_agent import events
from droid_agent.adb import Adb, AdbError
from droid_agent.device import DeviceOps

_STATIC = os.path.join(os.path.dirname(__file__), "static")


class _Fanout:
    """One producer, N subscriber queues (slow clients drop chunks)."""

    def __init__(self) -> None:
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self, prefix: bytes = b"") -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=16)
        if prefix:
            q.put(prefix)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, data: bytes) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(data)
            except queue.Full:
                pass


def _h264_loop(adb: Adb, size: tuple[int, int], fanout: _Fanout,
               header_box: list, stop: threading.Event) -> None:
    """Stream `screenrecord` h264 into the fanout; respawn on exit.

    screenrecord stops at its 180s time-limit and on some devices just
    dies — respawning is normal, not an error. Bytes up to the first IDR
    NAL (SPS/PPS + config) are kept in header_box so late-joining viewers
    can decode immediately.
    """
    w, h = size
    args = adb._base() + [
        "exec-out", "screenrecord",
        "--output-format=h264",
        "--size", f"{w}x{h}",
        "--bit-rate", "6000000",
        "--time-limit", "180",
        "-",
    ]
    while not stop.is_set():
        try:
            proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            stop.wait(2.0)
            continue
        header_box.clear()  # fresh SPS/PPS per stream start (size may change)
        header = bytearray()
        try:
            while not stop.is_set():
                chunk = proc.stdout.read(65536)  # type: ignore[union-attr]
                if not chunk:
                    break
                if not header_box:
                    header += chunk
                    # header complete once we see a start-code + IDR (type 5)
                    if b"\x00\x00\x00\x01\x65" in header \
                            or b"\x00\x00\x01\x65" in header:
                        header_box.append(bytes(header))
                fanout.publish(chunk)
        finally:
            proc.kill()
            proc.wait()
        stop.wait(0.4)


def _mjpeg_loop(adb: Adb, fanout: _Fanout, stop: threading.Event) -> None:
    """screencap -p on a timer — the fallback feed (~2fps)."""
    while not stop.is_set():
        try:
            png = adb.exec_out("screencap -p", timeout=10)
            if png.startswith(b"\x89PNG"):
                fanout.publish(png)
        except (AdbError, subprocess.TimeoutExpired, OSError):
            pass
        stop.wait(0.35)


def serve(serial: str | None, port: int = 8765, host: str = "127.0.0.1",
          force_mjpeg: bool = False, open_browser: bool = True) -> int:
    adb = Adb(serial=serial)
    adb.require_device()
    ops = DeviceOps(adb)
    try:
        size = ops.screen_size()
    except AdbError:
        size = (1080, 2400)
    model = adb.shell("getprop ro.product.model").strip() or "device"

    stop = threading.Event()
    h264_hub, mjpeg_hub = _Fanout(), _Fanout()
    header_box: list = []
    threads = []
    if not force_mjpeg:
        threads.append(threading.Thread(
            target=_h264_loop, args=(adb, size, h264_hub, header_box, stop),
            daemon=True))
    threads.append(threading.Thread(
        target=_mjpeg_loop, args=(adb, mjpeg_hub, stop), daemon=True))
    for t in threads:
        t.start()

    meta_cache: dict = {"t": 0.0, "w": size[0], "h": size[1]}

    def meta() -> dict:
        if time.time() - meta_cache["t"] > 1.5:
            try:
                w, h = ops.screen_size()
                meta_cache.update(t=time.time(), w=w, h=h)
            except AdbError:
                meta_cache["t"] = time.time()
        return {
            "w": meta_cache["w"], "h": meta_cache["h"],
            "model": model, "serial": adb.serial or "",
            "mode": "mjpeg" if force_mjpeg else "h264",
        }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet — the feed is the UI
            pass

        def _send(self, code: int, body: bytes,
                  ctype: str = "text/plain") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

        def _stream(self, fanout: _Fanout, boundary: str | None = None,
                    ctype: str = "application/octet-stream",
                    prefix: bytes = b"") -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = fanout.subscribe(prefix)
            try:
                while True:
                    try:
                        data = q.get(timeout=20)
                    except queue.Empty:
                        return
                    if boundary:
                        self.wfile.write(
                            f"--{boundary}\r\nContent-Type: image/png\r\n"
                            f"Content-Length: {len(data)}\r\n\r\n"
                            .encode())
                    self.wfile.write(data)
                    if boundary:
                        self.wfile.write(b"\r\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                fanout.unsubscribe(q)

        def _sse(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                for line in events.recent(20):
                    self.wfile.write(f"data: {line}\n\n".encode())
                self.wfile.flush()
            except OSError:
                return
            last_ka = time.time()
            for _, line in events.tail():  # starts at current EOF
                try:
                    if line:
                        self.wfile.write(f"data: {line}\n\n".encode())
                    elif time.time() - last_ka > 10:
                        self.wfile.write(b":ka\n\n")
                        last_ka = time.time()
                    else:
                        time.sleep(0.15)
                        continue
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return

        def do_GET(self):  # noqa: N802 — stdlib handler name
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            if path == "/":
                self._send(200, _HTML.encode(), "text/html; charset=utf-8")
            elif path == "/static/jmuxer.min.js":
                try:
                    with open(os.path.join(_STATIC, "jmuxer.min.js"),
                              "rb") as fh:
                        self._send(200, fh.read(), "application/javascript")
                except OSError:
                    self._send(404, b"not vendored")
            elif path == "/h264":
                self._stream(h264_hub, prefix=header_box[0] if header_box else b"")
            elif path == "/mjpeg":
                self._stream(mjpeg_hub, boundary="f",
                             ctype="multipart/x-mixed-replace; boundary=f")
            elif path == "/events":
                self._sse()
            elif path == "/meta":
                self._send(200, json.dumps(meta()).encode(),
                           "application/json")
            elif path == "/frame.png":
                try:
                    png = ops.screenshot()
                    self._send(200, png, "image/png")
                except AdbError as e:
                    self._send(502, str(e).encode())
            elif path == "/healthz":
                self._send(200, b"ok")
            else:
                self._send(404, b"not found")

    srv = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{srv.server_address[1]}"
    print(f"droid-agent watch → {url}  ({model}, "
          f"{'mjpeg' if force_mjpeg else 'h264+fallback'}) — Ctrl+C to stop")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        srv.server_close()
    return 0


_HTML = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>droid-agent · watch</title>
<style>
:root{color-scheme:dark;--bg:#0b0e14;--panel:#12151f;--line:#1f2430;
      --txt:#d7dce6;--dim:#7a8499;--acc:#6cf}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
     font:14px/1.4 ui-monospace,Consolas,monospace;height:100vh;
     display:flex;flex-direction:column}
header{display:flex;gap:14px;align-items:center;padding:10px 14px;
       border-bottom:1px solid var(--line)}
header b{color:var(--acc)}
#dev{color:var(--dim);font-size:12px}
.pill{margin-left:auto;font-size:11px;color:var(--dim);
      border:1px solid var(--line);border-radius:99px;padding:2px 10px}
main{flex:1;display:flex;min-height:0}
#stage{flex:1;position:relative;display:flex;align-items:center;
       justify-content:center;overflow:hidden;background:#000}
video,img#mjpeg{max-width:100%;max-height:100%;object-fit:contain}
#fx{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
#say{position:absolute;left:50%;bottom:26px;transform:translateX(-50%);
     max-width:80%;background:#12151fee;border:1px solid var(--acc);
     color:var(--txt);padding:8px 16px;border-radius:10px;font-size:15px;
     opacity:0;transition:opacity .25s;pointer-events:none}
#say.on{opacity:1}
aside{width:300px;border-left:1px solid var(--line);overflow-y:auto;
      background:var(--panel);padding:8px}
aside .e{padding:6px 8px;border-bottom:1px solid var(--line);
         font-size:12px;color:var(--dim)}
aside .e b{color:var(--txt);font-weight:600}
aside .e.say{border-left:2px solid var(--acc);color:var(--txt)}
</style>
<header>
  <b>droid-agent</b> watch
  <span id="dev">connecting…</span>
  <span class="pill" id="mode">…</span>
</header>
<main>
  <section id="stage">
    <video id="v" muted autoplay playsinline></video>
    <img id="mjpeg" alt="">
    <canvas id="fx"></canvas>
    <div id="say"></div>
  </section>
  <aside id="log"></aside>
</main>
<script src="/static/jmuxer.min.js"></script>
<script>
"use strict";
let devW = 1080, devH = 2400;
const stage = document.getElementById("stage");
const video = document.getElementById("v");
const img   = document.getElementById("mjpeg");
const cv    = document.getElementById("fx");
const ctx   = cv.getContext("2d");
const log   = document.getElementById("log");
const sayEl = document.getElementById("say");
img.style.display = "none";

// device px -> displayed px (video is object-fit:contain → letterbox)
function map(x, y) {
  const s = Math.min(stage.clientWidth / devW, stage.clientHeight / devH);
  const ox = (stage.clientWidth - devW * s) / 2;
  const oy = (stage.clientHeight - devH * s) / 2;
  return [ox + x * s, oy + y * s];
}
function fit() {
  cv.width = stage.clientWidth; cv.height = stage.clientHeight;
}
new ResizeObserver(fit).observe(stage); fit();

const fx = [];
function ripple(x, y, big) {
  const [px, py] = map(x, y);
  fx.push({t0: performance.now(), life: big ? 1100 : 750, draw(c, k) {
    const r = (big ? 60 : 42) * k + 8, a = 1 - k;
    c.beginPath(); c.arc(px, py, r, 0, 7);
    c.strokeStyle = `rgba(108,204,255,${a})`; c.lineWidth = 3; c.stroke();
    c.beginPath(); c.arc(px, py, 5, 0, 7);
    c.fillStyle = `rgba(108,204,255,${a})`; c.fill();
  }});
}
function arrow(x1, y1, x2, y2) {
  const [ax, ay] = map(x1, y1), [bx, by] = map(x2, y2);
  fx.push({t0: performance.now(), life: 700, draw(c, k) {
    const t = Math.min(1, k * 1.4), ex = ax + (bx - ax) * t, ey = ay + (by - ay) * t;
    c.beginPath(); c.moveTo(ax, ay); c.lineTo(ex, ey);
    c.strokeStyle = `rgba(108,204,255,${1 - k})`; c.lineWidth = 4;
    c.lineCap = "round"; c.stroke();
  }});
}
function flash() {
  fx.push({t0: performance.now(), life: 350, draw(c, k) {
    c.fillStyle = `rgba(255,255,255,${0.5 * (1 - k)})`;
    c.fillRect(0, 0, cv.width, cv.height);
  }});
}
(function loop() {
  const now = performance.now();
  ctx.clearRect(0, 0, cv.width, cv.height);
  for (let i = fx.length - 1; i >= 0; i--) {
    const k = (now - fx[i].t0) / fx[i].life;
    if (k >= 1) { fx.splice(i, 1); continue; }
    fx[i].draw(ctx, k);
  }
  requestAnimationFrame(loop);
})();

function line(kind, txt) {
  const d = document.createElement("div");
  d.className = "e" + (kind === "say" ? " say" : "");
  d.textContent = txt;
  if (kind === "say") d.style.color = "#d7dce6";
  log.prepend(d);
  while (log.children.length > 60) log.lastChild.remove();
}
let sayT;
function narrate(t) {
  sayEl.textContent = t; sayEl.classList.add("on");
  clearTimeout(sayT);
  sayT = setTimeout(() => sayEl.classList.remove("on"), 3500);
}
const hm = t => new Date(t * 1000).toLocaleTimeString("en-GB");
function onEvent(ev) {
  switch (ev.kind) {
    case "tap":        ripple(ev.x, ev.y); line("tap", `${hm(ev.t)} tap “${ev.label}”`); break;
    case "long_press": ripple(ev.x, ev.y, true);
      line("tap", `${hm(ev.t)} long-press “${ev.label}”`); break;
    case "swipe":      arrow(ev.x1, ev.y1, ev.x2, ev.y2); line("swipe", `${hm(ev.t)} swipe`); break;
    case "type":       line("type", `${hm(ev.t)} typed ${ev.chars} chars`); break;
    case "key":        line("key", `${hm(ev.t)} key ${ev.name}`); break;
    case "shell":      line("shell", `${hm(ev.t)} $ ${ev.cmd}`); break;
    case "unlock":     line("unlock", `${hm(ev.t)} unlock`); break;
    case "launch":     line("app", `${hm(ev.t)} open ${ev.package}`); break;
    case "stop":       line("app", `${hm(ev.t)} close ${ev.package}`); break;
    case "clear":      line("app", `${hm(ev.t)} cleared ${ev.package}`); break;
    case "install":    line("app", `${hm(ev.t)} install ${ev.apk}`); break;
    case "uninstall":  line("app", `${hm(ev.t)} uninstall ${ev.package}`); break;
    case "push":       line("fs", `${hm(ev.t)} push → ${ev.remote}`); break;
    case "pull":       line("fs", `${hm(ev.t)} pull ${ev.remote}`); break;
    case "connect":    line("fs", `${hm(ev.t)} connect ${ev.target}`); break;
    case "disconnect": line("fs", `${hm(ev.t)} disconnect`); break;
    case "dump":       line("see", `${hm(ev.t)} dumped UI`); break;
    case "find":       line("see", `${hm(ev.t)} find “${ev.text}”`); break;
    case "read":       line("see", `${hm(ev.t)} read screen`); break;
    case "screenshot": flash(); line("see", `${hm(ev.t)} screenshot`); break;
    case "say":        narrate(ev.text); line("say", `${hm(ev.t)} “${ev.text}”`); break;
    default:           line("", `${hm(ev.t)} ${ev.kind}`);
  }
}
const es = new EventSource("/events");
es.onmessage = e => { try { onEvent(JSON.parse(e.data)); } catch (_) {} };

// video: h264 via stock screenrecord -> jmuxer/MSE; fallback to MJPEG
let fellBack = false;
function fallback() {
  if (fellBack) return; fellBack = true;
  video.style.display = "none"; img.style.display = "";
  img.src = "/mjpeg";
  document.getElementById("mode").textContent = "mjpeg";
  line("sys", "h264 unavailable → mjpeg fallback");
}
async function feed() {
  try {
    const res = await fetch("/h264");
    if (!res.ok || !res.body) return fallback();
    const jm = new JMuxer({node: "v", mode: "video", fps: 30,
                           flushingTime: 400, debug: false});
    const rd = res.body.getReader();
    let got = 0;
    const t0 = Date.now();
    for (;;) {
      const {done, value} = await rd.read();
      if (done) break;
      got += value.length;
      try { jm.feed({video: value}); } catch (_) {}
    }
    if (got === 0 || Date.now() - t0 < 3000) fallback();
    else fallback();
  } catch (_) { fallback(); }
}
feed();

async function meta(first) {
  try {
    const m = await (await fetch("/meta")).json();
    if (first) { devW = m.w; devH = m.h; }
    else if (m.w !== devW || m.h !== devH) location.reload();
    document.getElementById("dev").textContent =
      `${m.model} · ${m.serial} · ${m.w}×${m.h}`;
    if (!fellBack) document.getElementById("mode").textContent = m.mode;
  } catch (_) {}
}
meta(true); setInterval(() => meta(false), 2000);
</script>
"""
