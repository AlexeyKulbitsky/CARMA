import shutil

import pytest

from carma import __version__
from carma.cli import COMMANDS, main
from carma.config import load_config

IMPLEMENTED = {"index", "init", "check", "serve"}


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


def test_check_reports_the_planted_issues(golden_project, capsys):
    assert main(["check", "--project", str(golden_project)]) == 1
    out = capsys.readouterr().out
    assert "undeclared_dependency  streaming -> render" in out and "cycle                  render <-> streaming" in out
    assert "0 unassigned" in out and out.rstrip().endswith("2 issues")


def test_check_without_issues_and_without_facts(golden_project, capsys):
    for name in ("render", "render.backend", "streaming"):  # the cycle goes with them
        (golden_project / ".carma" / "model" / f"{name}.yaml").unlink()
    assert main(["check", "--project", str(golden_project)]) == 0
    out = capsys.readouterr().out
    assert "3 components" in out and "35 unassigned" in out and out.rstrip().endswith("no issues")
    shutil.rmtree(golden_project / ".carma" / "cache")
    assert main(["check", "--project", str(golden_project)]) == 2
    assert "run carma index first" in capsys.readouterr().err


def test_init_writes_the_skeleton_from_indexed_folders(make_golden, golden_dir, capsys):
    project = make_golden(model=False)
    (project / ".carma" / "config.yaml").unlink()
    (project / "build").mkdir()
    (project / "build" / "compile_commands.json").write_text("[]", encoding="utf-8")
    code = main(["init", "--project", str(project), "--source-root", str(project / "src"),
                 "--source-root", str(project / "apps")])
    assert code == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert "created .carma/config.yaml (compile_commands: build/compile_commands.json)" in out
    config = load_config(project)
    assert config.compile_commands == "build/compile_commands.json" and config.source_roots == ("src", "apps")
    assert (project / ".carma" / ".gitignore").read_text(encoding="utf-8") == "cache/\n"
    written = sorted(p.stem for p in (project / ".carma" / "model").glob("*.yaml"))
    assert written == sorted(p.stem for p in (golden_dir / "expected" / "model").glob("*.yaml"))
    assert "render.backend  component  src/render/backend/**" in out

    # a second run leaves the model alone
    assert main(["init", "--project", str(project)]) == 0
    assert "6 component files exist, the skeleton is not written" in capsys.readouterr().out


def test_init_needs_compile_commands_and_roots_inside_the_project(tmp_path, capsys):
    assert main(["init", "--project", str(tmp_path)]) == 2
    assert "pass --compile-commands or --cmake-build-dir" in capsys.readouterr().err
    (tmp_path / "compile_commands.json").write_text("[]", encoding="utf-8")
    assert main(["init", "--project", str(tmp_path), "--source-root", str(tmp_path.parent)]) == 2
    assert "must be inside the project" in capsys.readouterr().err
    assert not (tmp_path / ".carma").exists()


def test_init_finds_a_cmake_build_folder(make_golden):
    project = make_golden(model=False)
    (project / ".carma" / "config.yaml").unlink()
    (project / "build").mkdir()
    (project / "build" / "CMakeCache.txt").write_text("", encoding="utf-8")
    assert main(["init", "--project", str(project)]) == 0
    config = load_config(project)
    assert (config.cmake_build_dir, config.configuration, config.source_roots) == ("build", "Debug", ())
    assert (project / ".carma" / "model" / "src.yaml").is_file()  # no source roots: the skeleton starts at the root
