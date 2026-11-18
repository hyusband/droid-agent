from droid_agent.cli import build_parser, main


def test_help_lists_commands(capsys):
    try:
        main(["--help"])
    except SystemExit as e:
        assert e.code == 0
    out = capsys.readouterr().out
    for cmd in ("devices", "dump", "tap", "type", "swipe", "key",
                "screenshot", "open", "state", "mcp"):
        assert cmd in out


def test_version(capsys):
    try:
        main(["--version"])
    except SystemExit as e:
        assert e.code == 0
    assert "droid-agent" in capsys.readouterr().out


def test_parser_subcommands():
    p = build_parser()
    a = p.parse_args(["tap", "3"])
    assert a.command == "tap" and a.target == "3"
    a = p.parse_args(["swipe", "up"])
    assert a.direction == "up"
    a = p.parse_args(["--json", "dump"])
    assert a.json and a.command == "dump"
    a = p.parse_args(["-s", "emulator-5554", "devices"])
    assert a.serial == "emulator-5554"
