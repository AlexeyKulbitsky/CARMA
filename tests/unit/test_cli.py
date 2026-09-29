import pytest

from carma import __version__
from carma.cli import COMMANDS, main


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_unimplemented_commands_say_which_milestone(command, capsys):
    assert main([command]) == 2
    assert COMMANDS[command][1] in capsys.readouterr().err
