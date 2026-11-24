# Security Policy

## Threat model

`droid-agent` is a remote-control tool: the MCP server (and the CLI)
expose full hands on any device reachable over `adb` — raw `shell`,
`install`/`uninstall`/`clear_data`, `push_file`/`pull_file`, `connect`
to arbitrary hosts, and UI gestures. That is the feature, not a bug, but
it means the **capability surface is critical**: an agent that is
manipulated (e.g. by indirect prompt injection) can do real damage.

The main injection surface is indirect prompt injection: a malicious app
can place prompt-looking text in element labels, `content-desc`, logs or
on the screen itself, which the agent then reads via `dump_ui`, `find`,
`logcat`, `shell` or `screenshot`.

## Built-in mitigations

- **Password masking** — `password="true"` elements are stripped from
  dumps and never persisted to `~/.droid-agent/session.json`.
- **Injection scrubbing** — invisible Unicode (zero-width spaces/joiners,
  bidi overrides/isolates, tag chars) and C0/C1 controls are stripped
  from `label`/`text`/`desc`, so hidden instructions don't reach the model.
- **Tool tiers** (`droid-agent mcp …` or env vars):
  - `--safe` / `DROID_AGENT_SAFE` — destructive tools are not registered
    (`shell`, `install`, `uninstall`, `clear_data`, `push_file`,
    `pull_file`, `connect`, `disconnect`)
  - `--readonly` / `DROID_AGENT_READONLY` — observe-only tools
    (`devices`, `dump_ui`, `find`, `device_state`, `logcat`,
    `list_packages`, `is_installed`, `wait_for`, `screenshot`)
  - `--confirm` / `DROID_AGENT_CONFIRM` — destructive ops require a
    one-time `code` printed to the server console (stderr), so text the
    model reads can never satisfy the gate

## Recommended posture

- Running an unattended agent on a personal device: use `--safe` or
  `--readonly`, or `--confirm` if destructive ops are needed.
- The `shell` tool is an intentional escape hatch — treat it as root of
  the capability surface; under `--confirm` it requires the console code.
- `connect` accepts any `host:port` — adb-over-TCP trusts the network;
  only pair/connect to devices you control on trusted networks.

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.3.x   | yes       |
| < 0.3   | best-effort — upgrade |

## Reporting a vulnerability

Use
[GitHub private vulnerability reporting](https://github.com/hyusband/droid-agent/security)
(preferred) or open an issue without the exploit details. Please do not
open public issues for unpatched vulnerabilities.
