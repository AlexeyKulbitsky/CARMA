from pathlib import Path

from carma.compiledb import CompileCommand
from carma.indexers.libclang.args import libclang_args


def command(tmp_path, *args):
    source = tmp_path / "src" / "a.cpp"
    return CompileCommand(directory=tmp_path, file=source, arguments=args)


def test_msvc_command(tmp_path):
    cmd = command(tmp_path, "C:/VS/cl.exe", "/DWIN32", "/EHsc", "/MDd", "/Zi", "/RTC1", "/Fo" + "x.obj", "/Fdx.pdb",
                  "/Yupch.h", "/Fpx.pch", "-std:c++20", "/c", str(tmp_path / "src" / "a.cpp"))
    assert libclang_args(cmd) == ["--driver-mode=cl", "/DWIN32", "/EHsc", "/MDd", "-std:c++20"]


def test_gnu_command(tmp_path):
    cmd = command(tmp_path, "/usr/bin/c++", "-Isrc", "-DX", "-MD", "-MF", "a.d", "-MT", "a.o", "-o", "a.o",
                  "-Xclang", "-include-pch", "-Xclang", "pch.pch", "-std=gnu++20", "-c", "src/a.cpp")
    assert libclang_args(cmd) == ["-Isrc", "-DX", "-std=gnu++20"]


def test_response_file(tmp_path):
    (tmp_path / "flags.rsp").write_text("-DFROM_RSP -Iinc", encoding="utf-8")
    cmd = command(tmp_path, "clang++", "@flags.rsp", "-c", "src/a.cpp")
    assert libclang_args(cmd) == ["-DFROM_RSP", "-Iinc"]


def test_source_file_matched_by_path_not_by_name(tmp_path):
    other = str(Path("other") / "a.cpp")
    cmd = command(tmp_path, "clang++", "-include", other, "src/a.cpp")
    assert libclang_args(cmd) == ["-include", other]


def test_resource_dir_and_sysroot(tmp_path):
    cmd = command(tmp_path, "/usr/bin/c++", "-std=c++20", "-c", "src/a.cpp")
    assert libclang_args(cmd, resource_dir="/llvm/lib/clang/21", sysroot="/sdk") == [
        "-std=c++20", "-resource-dir", "/llvm/lib/clang/21", "-isysroot", "/sdk"]


def test_sysroot_from_the_command_wins(tmp_path):
    cmd = command(tmp_path, "/usr/bin/c++", "-isysroot", "/own/sdk", "-c", "src/a.cpp")
    assert libclang_args(cmd, sysroot="/sdk") == ["-isysroot", "/own/sdk"]
