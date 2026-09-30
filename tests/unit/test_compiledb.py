import json
import os
from pathlib import Path

import pytest

from carma.compiledb import CompileCommand, from_cmake_build, from_compile_commands
from carma.compiledb.shell import split_windows


@pytest.mark.parametrize(
    "command,expected",
    [
        ('cl.exe /c "a b.cpp"', ["cl.exe", "/c", "a b.cpp"]),
        (r'cl /I"C:\my dir\inc" /DX', ["cl", r"/IC:\my dir\inc", "/DX"]),
        (r'cl /DNAME=\"v\"', ["cl", '/DNAME="v"']),
        (r'cl C:\path\to\file.cpp', ["cl", r"C:\path\to\file.cpp"]),
        (r'cl "C:\trailing\\"', ["cl", "C:\\trailing\\"]),
        ('a  "" b', ["a", "", "b"]),
    ],
)
def test_split_windows(command, expected):
    assert split_windows(command) == expected


def test_compile_commands_json(tmp_path):
    db = tmp_path / "compile_commands.json"
    db.write_text(json.dumps([
        {"directory": str(tmp_path / "build"), "file": "../src/a.cpp", "arguments": ["clang++", "-Isrc", "-c", "../src/a.cpp"]},
        {"directory": str(tmp_path / "build"), "file": str(tmp_path / "src" / "a.cpp"), "arguments": ["clang++", "-DDUP", "-c", "x"]},
        {"directory": str(tmp_path / "build"), "file": "../src/b.cpp", "command": "clang++ -DB -c ../src/b.cpp"},
    ]), encoding="utf-8")
    commands = from_compile_commands(db)
    assert [c.file.name for c in commands] == ["a.cpp", "b.cpp"]  # the duplicate of a.cpp is dropped
    assert commands[0].file == Path(os.path.normpath(tmp_path / "src" / "a.cpp"))
    assert "-DB" in commands[1].arguments


def test_cl_mode():
    assert CompileCommand(Path("."), Path("a.cpp"), ("C:/VS/bin/cl.exe", "/c")).cl_mode
    assert CompileCommand(Path("."), Path("a.cpp"), ("clang-cl", "/c")).cl_mode
    assert not CompileCommand(Path("."), Path("a.cpp"), ("/usr/bin/c++", "-c")).cl_mode
    assert CompileCommand(Path("."), Path("a.cpp"), ("clang++", "--driver-mode=cl")).cl_mode


def write_reply(build: Path, source_root: Path, compiler: str, fragments: str) -> None:
    """A minimal CMake File API reply: one configuration, one target, one compile group."""
    reply = build / ".cmake" / "api" / "v1" / "reply"
    reply.mkdir(parents=True)
    (reply / "codemodel-v2-1.json").write_text(json.dumps({
        "paths": {"source": str(source_root), "build": str(build)},
        "configurations": [
            {"name": "Release", "targets": []},
            {"name": "Debug", "targets": [{"name": "core", "jsonFile": "target-core.json"}]},
        ],
    }), encoding="utf-8")
    (reply / "target-core.json").write_text(json.dumps({
        "paths": {"source": ".", "build": "."},
        "compileGroups": [{
            "language": "CXX",
            "languageStandard": {"standard": "20"},
            "compileCommandFragments": [{"fragment": fragments}],
            "includes": [{"path": str(source_root / "src")}, {"path": str(source_root / "sys"), "isSystem": True}],
            "defines": [{"define": "CORE=1"}],
        }],
        "sources": [
            {"path": "src/a.cpp", "compileGroupIndex": 0},
            {"path": "src/a.h"},
            {"path": "src/b.h", "compileGroupIndex": 0},
        ],
    }), encoding="utf-8")
    (reply / "toolchains-v1-1.json").write_text(json.dumps({
        "toolchains": [{"language": "CXX", "compiler": {"path": compiler, "id": "X"}}],
    }), encoding="utf-8")
    (reply / "index-2026-01-01T00-00-00-0000.json").write_text(json.dumps({
        "reply": {"client-carma": {"query.json": {"responses": [
            {"kind": "codemodel", "jsonFile": "codemodel-v2-1.json"},
            {"kind": "toolchains", "jsonFile": "toolchains-v1-1.json"},
        ]}}},
    }), encoding="utf-8")


def test_cmake_file_api_gnu(tmp_path):
    source, build = tmp_path / "src_root", tmp_path / "build"
    write_reply(build, source, "/usr/bin/c++", "-O2 -Wall")
    [cmd] = from_cmake_build(build, reconfigure=False)  # headers and sources without a compile group are skipped
    assert cmd.file == Path(os.path.normpath(source / "src" / "a.cpp"))
    args = list(cmd.arguments)
    assert args[0] == "/usr/bin/c++" and "-O2" in args and "-DCORE=1" in args and "-std=c++20" in args
    assert "-I" + str(source / "src") in args and args[args.index("-isystem") + 1] == str(source / "sys")
    assert (build / ".cmake" / "api" / "v1" / "query" / "client-carma" / "query.json").is_file()


def test_cmake_file_api_msvc(tmp_path):
    source, build = tmp_path / "src_root", tmp_path / "build"
    write_reply(build, source, "C:/VS/bin/cl.exe", "/DWIN32 /EHsc -std:c++20")
    [cmd] = from_cmake_build(build, "Debug", reconfigure=False)
    args = list(cmd.arguments)
    assert cmd.cl_mode and "/DCORE=1" in args and "/I" + str(source / "src") in args and "/imsvc" + str(source / "sys") in args
    assert "-std:c++20" in args and not any(a.startswith("/std") for a in args)  # the fragment already has it


def test_unknown_configuration(tmp_path):
    from carma.compiledb import CompileDbError

    write_reply(tmp_path / "build", tmp_path, "/usr/bin/c++", "")
    with pytest.raises(CompileDbError, match="RelWithDebInfo"):
        from_cmake_build(tmp_path / "build", "RelWithDebInfo", reconfigure=False)
