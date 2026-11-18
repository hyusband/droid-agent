# Show HN draft — launch copy

**Title:** Show HN: droid-agent – control Android via adb, no on-device install

**Post:**

Every Android automation tool for AI agents asks you to install something on
the phone first — Appium's server, a companion APK, an accessibility service.
I wanted the opposite: give an agent hands using only stock adb, which every
dev/emulator already has.

`droid-agent dump` runs `uiautomator dump`, then distills the XML hierarchy
into a browser-use-style numbered list of *actionable* elements — buttons,
inputs, scrollables — with stable refs. `droid-agent tap 3` resolves the ref
to its center point. Re-dump, verify, repeat. The whole thing is ~1k lines of
stdlib-only Python with `--json` on every command, plus a built-in MCP server
(`pipx install 'droid-agent[mcp]'`, then one JSON block in your agent config).

Design choices that might be interesting:

- The ref map persists to disk per session with a staleness timer — tapping a
  ref from a 3-minute-old screen is how agents click the wrong thing, so it
  warns instead.
- Clickable parents absorb their children's text as the label (a Button
  wrapping a TextView shows as `button "ACTIVAR"`, not two rows).
- Password fields are masked in dumps so agents don't leak credentials into
  logs.
- Zero deps and ~300ms startup — meant to be called 50×/session, not once.

Works on real phones, emulators, Android TV/x86 — anything adb reaches.
MIT licensed: https://github.com/hyusband/droid-agent

Happy to answer questions; especially curious what element-detection edge
cases break for you.
