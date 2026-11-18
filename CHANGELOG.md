# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
