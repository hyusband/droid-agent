<!-- mcp-name: io.github.hyusband/droid-agent -->
<div align="center">

# 🤖 droid-agent

**Give any AI agent hands on a real Android device — zero install on the phone.**

`dump` a screen → get numbered interactive elements → `tap 3`. That's it.

[![CI](https://github.com/hyusband/droid-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/hyusband/droid-agent/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/droid-agent)](https://pypi.org/project/droid-agent/)
[![Python](https://img.shields.io/pypi/pyversions/droid-agent)](https://pypi.org/project/droid-agent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

![demo](assets/demo.gif)

</div>

## Why

Every other Android-agent tool makes you install something **on the phone**
first — an Appium server, a companion APK, an accessibility service.
`droid-agent` needs **nothing on the device**. Just `adb`, which you already
have:

- 🔢 **browser-use for Android** — `dump` distills the uiautomator tree into a
  short numbered list of actionable refs, not a 500-line XML blob
- 📦 **zero dependencies** — pure stdlib, installs in <1s, works offline
- 🤖 **agent-first** — every command has `--json`; ships a built-in MCP server
- 📱 **anything with adb** — real phones, emulators, Android TVs, Android Auto,
  WSA, even Android-x86 VMs

## Install

```bash
pipx install droid-agent          # recommended
# or: pip install droid-agent

pipx install 'droid-agent[mcp]'   # + MCP server for Claude Code / Cursor / Devin
```

Prerequisite: [platform-tools](https://developer.android.com/tools/releases/platform-tools)
(`adb`) on your `PATH`, and a device with USB or wireless debugging enabled.

## 60-second tour

```bash
droid-agent devices                 # what's attached
droid-agent connect 192.168.1.42    # wireless adb (or just plug USB)
droid-agent dump                    # see the screen the way an agent does
```

Real output, straight off a POCO F5:

```text
[ 1] ()    Search settings                                  ( 540, 497)
[ 2] |||   recyclerview                                     ( 540,1487)
[ 3] ()    About phone                                      ( 540, 663)
[ 4] ()    System apps updater                              ( 540, 817)
[ 5] ()    Security status                                  ( 540, 971)
[ 6] ()    Wi-Fi                                            ( 540,1159)
[ 7] ()    Bluetooth                                        ( 540,1313)
[ 8] ()    Mobile networks                                  ( 540,1467)
[ 9] ()    Interconnectivity                                ( 540,1621)

15 elements · tap with `droid-agent tap <ref>`
```

```bash
droid-agent tap 3                   # taps "About phone"
droid-agent type "me@x.com"         # types into the focused field
droid-agent swipe up                # scroll the list
droid-agent key back                # keyevents by name
droid-agent open com.whatsapp       # launch any app
droid-agent screenshot shot.png     # PNG capture
droid-agent state                   # foreground app, screen on/off, size
```

For agents, everything is one flag away from JSON: `droid-agent --json dump`.

## Use it with your agent (MCP)

```json
{
  "mcpServers": {
    "droid-agent": { "command": "droid-agent", "args": ["mcp"] }
  }
}
```

29 tools exposed — the primitives (`tap`, `swipe`, `key`, `dump_ui`, `shell`)
plus compound workflows that save agent round-trips: `tap_text` ("tap the
Allow button" in one call), `type_into` (tap field + type), `wait_for` /
`scroll_until` (dynamic waits), `find` (query the UI tree), `screenshot`
(real image content for vision), `logcat`, `install`/`uninstall`, and file
`push`/`pull`. A built-in `android_task` prompt teaches any agent the
dump → act → verify loop.

Also listed in the [official MCP Registry](https://registry.modelcontextprotocol.io/)
as `io.github.hyusband/droid-agent`.

## Commands

| Command | What it does |
| --- | --- |
| `devices` | list attached devices + state |
| `connect` / `pair` / `disconnect` | wireless adb (Android 11+ pairing supported) |
| `dump` | numbered interactive elements → `~/.droid-agent/session.json` |
| `tap <ref\|x,y>` / `long-press` | touch by ref from last dump, or raw coords |
| `type <text>` | input text (spaces handled) into focused field |
| `swipe up\|down\|left\|right` or `x1 y1 x2 y2` | scroll / gestures |
| `key back\|home\|enter\|tab\|del\|power…` | keyevents by name |
| `open` / `close` / `install` / `uninstall` | app lifecycle |
| `screenshot` / `state` | PNG capture · foreground app + screen info |
| `shell <cmd>` | raw adb escape hatch |
| `mcp` | stdio MCP server |

## How it compares

| | droid-agent | droidrun/mobilerun | mobile-mcp | Appium |
| --- | --- | --- | --- | --- |
| On-device install | **none** | Portal APK + accessibility svc | Appium driver | Appium server + settings app |
| Time to first `tap` | **seconds** | minutes | minutes | ~30 min |
| What it is | primitive layer | full agent framework | MCP bridge | test framework |
| Deps | **0** (stdlib) | LLM SDKs, uv, portal | node, appium | java/node stack |
| LLM coupling | none — BYO agent | built-in providers | none | none |

Different tool for a different job: they're agent *frameworks*; this is the
`curl` of Android control — a primitive layer any agent (or human) can call.

## Agent workflow pattern

```text
dump → read refs → tap/type → wait → dump → verify → repeat
```

The dump warns when refs are >120s old (the UI may have moved). `tap` on a
missing ref tells you to re-dump instead of tapping blind.

## FAQ

**Does it need root?** No — just USB/wireless debugging enabled.

**iOS?** No. Use [`iphone-cli`](https://github.com/HyunSeob/iphone-cli) — this one is
Android-only by design.

**Passwords?** Elements flagged `password="true"` are masked in dumps and
never persisted to the session file.

**CI?** Point it at an emulator (`emulator-5554`) — same interface, `--json`
for parsing.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and false-positive
element-detection reports especially welcome — attach `droid-agent dump --json`
plus a screenshot.

## License

MIT — see [LICENSE](LICENSE).

---

<div align="center">
If this saved you a setup afternoon — drop a ⭐
</div>
