from pathlib import Path

from carma.indexers.libclang.discovery import LibclangInfo, resource_dir


def fake_llvm(root: Path, library: str, version: str = "21.1.8") -> LibclangInfo:
    lib = root / library
    lib.parent.mkdir(parents=True)
    lib.write_bytes(b"")
    headers = root / "lib" / "clang" / version.split(".")[0] / "include"
    headers.mkdir(parents=True)
    (headers / "stddef.h").write_text("", encoding="utf-8")
    return LibclangInfo(path=lib, version=f"clang version {version}", number=version, major=int(version.split(".")[0]))


def test_resource_dir_next_to_a_unix_library(tmp_path):
    info = fake_llvm(tmp_path / "llvm", "lib/libclang.so")
    assert resource_dir(info) == (tmp_path / "llvm" / "lib" / "clang" / "21").resolve()


def test_resource_dir_next_to_a_windows_library(tmp_path):
    info = fake_llvm(tmp_path / "LLVM", "bin/libclang.dll")
    assert resource_dir(info) == (tmp_path / "LLVM" / "lib" / "clang" / "21").resolve()


def test_no_resource_dir(tmp_path):
    lib = tmp_path / "lib" / "libclang.so"
    lib.parent.mkdir(parents=True)
    lib.write_bytes(b"")
    info = LibclangInfo(path=lib, version="clang version 21.1.8", number="21.1.8", major=21)
    assert resource_dir(info) is None
