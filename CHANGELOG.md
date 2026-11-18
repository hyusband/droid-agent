# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-11-18

### Added
- MCP server grew from 12 to 29 tools: `find`, `tap_text`, `type_into`,
  `wait_for`, `scroll_until` (compound agent workflows), `long_press`,
  `swipe_xy`, `shell`, `logcat`, `list_packages`, `install`, `uninstall`,
  `clear_data`, `is_installed`, `push_file`, `pull_file`, `connect`,
  `disconnect`
- `screenshot` now returns a real MCP image content block (rendered by
  clients) instead of base64 text
- `android_task` MCP prompt describing the dump → act → verify loop
- `ui.find_elements` — substring/exact text search with kind/clickable/
  editable filters

### Fixed
- `mcp` extra pinned `<2` — mcp SDK 2.x renamed `FastMCP` and broke the
  server import

## [0.1.2] - 2026-11-19

### Added
- `server.json` for the official MCP Registry — tag releases now publish
  to PyPI and the registry (`io.github.hyusband/droid-agent`) via GitHub OIDC

## [0.1.1] - 2026-11-19

### Changed
- Demo GIF replaced with a real VHS-recorded terminal session (no simulated UI)
- README redesigned (centered header, real POCO F5 output, fixed links)
- CI: pinned ubuntu-24.04 for Python 3.9 coverage, trimmed macOS matrix
  to the two latest Pythons, bash-shell CLI smoke step
- PyPI publishing via repository secret (fallback until trusted
  publishing is configured)

## [0.1.0] - 2026-11-19

### Added
- Core CLI: `devices`, `connect`, `pair`, `disconnect`, `dump`, `tap`,
  `long-press`, `swipe`, `type`, `key`, `wait`, `open`, `close`, `install`,
  `uninstall`, `screenshot`, `state`, `shell`, `mcp`
- Numbered interactive-element refs distilled from uiautomator XML
  (browser-use-style), persisted per session at `~/.droid-agent/session.json`
- Stale-ref detection (>120s) with re-dump hint
- `--json` output mode on every command for agent consumption
- MCP stdio server (`droid-agent[mcp]` extra) exposing 12 tools
- Wireless pairing support for Android 11+
- Password-field masking in dumps
