# Contributing to droid-agent

Thanks for helping! This project stays intentionally small: **zero runtime
dependencies** and **no device-side installs** are hard constraints — every
contribution is weighed against them.

## Setup

```bash
git clone https://github.com/FEKA/droid-agent
cd droid-agent
pip install -e '.[dev]'
python -m pytest
```

## Ground rules

1. **No new runtime dependencies.** Everything in `src/droid_agent/` is
   stdlib-only. Optional extras (like `mcp`) live behind extras and must be
   import-guarded.
2. **Every failure must be explainable.** If adb/device/user input can fail,
   the error must say *why* and *what to try* — never a bare traceback.
   Raise `AdbError` with a useful message; the CLI turns it into a clean exit.
3. **`--json` is a contract.** Agents consume it. Keys are snake_case,
   errors go to stderr, stdout stays parseable. Don't print decoration in
   JSON mode.
4. **Refs are sacred.** Element numbering must be deterministic for a given
   hierarchy — tests in `tests/test_ui.py` pin the ordering.

## Testing

- Unit tests run without a device: `python -m pytest`
- Fixtures live in `tests/fixtures/` — add a `uiautomator dump` capture when
  fixing an element-detection bug. Sanitize package names if needed.
- Adversarial coverage lives in `tests_adversarial/` — breakage found in the
  wild should land there with a repro.

## Pull requests

- One change per PR; describe the *why*.
- Run `ruff check src tests` and `python -m pytest` before pushing.
- Update `CHANGELOG.md` under an `Unreleased` heading.
- New CLI flags/commands need README table entries.

## Reporting bugs

Open an issue with:

- `droid-agent --version`, Android version, device/emulator
- the exact command you ran
- `droid-agent dump --json` output + a screenshot if it's a UI-detection bug
- what you expected vs what happened
