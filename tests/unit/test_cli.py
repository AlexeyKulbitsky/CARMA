import pytest

from carma import __version__
from carma.cli import COMMANDS, main

IMPLEMENTED = {"index"}


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


@pytest.mark.parametrize("command", sorted(set(COMMANDS) - IMPLEMENTED))
def test_unimplemented_commands_say_which_milestone(command, capsys):
    assert main([command]) == 2
    assert COMMANDS[command][1] in capsys.readouterr().err


def test_index_without_config(tmp_path, capsys):
    assert main(["index", "--project", str(tmp_path)]) == 2
    assert "config.yaml" in capsys.readouterr().err
