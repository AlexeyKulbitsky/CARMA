"""Finding and loading libclang from an installed LLVM.

Search order: CARMA_LIBCLANG → indexer.libclang in config.yaml → LLVM_PATH → llvm-config →
standard install locations. The Python bindings (the `clang` package) are used with the
strict compatibility check off, so bindings newer than the library still load; every
function the adapter calls exists in libclang 19.
"""

from __future__ import annotations

import ctypes
import glob
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MIN_MAJOR = 19


class LibclangError(Exception):
    pass


@dataclass(frozen=True)
class LibclangInfo:
    path: Path
    version: str  # full version string, e.g. "clang version 21.1.7"
    number: str  # e.g. "21.1.7"
    major: int


def _library_names() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("libclang.dll",)
    if sys.platform == "darwin":
        return ("libclang.dylib",)
    return ("libclang.so", "libclang.so.1")


def _version_key(path: str) -> tuple[int, ...]:
    numbers = re.findall(r"(\d+)", path)
    return tuple(int(n) for n in numbers[-3:]) if numbers else (0,)


def _in_llvm_prefix(prefix: Path) -> list[Path]:
    folders = [prefix / "bin", prefix / "lib"] if sys.platform == "win32" else [prefix / "lib", prefix / "lib64"]
    return [folder / name for folder in folders for name in _library_names()]


def _llvm_config() -> list[Path]:
    tool = shutil.which("llvm-config")
    if not tool:
        return []
    found = []
    for flag in ("--bindir", "--libdir"):
        try:
            out = subprocess.run([tool, flag], capture_output=True, text=True, check=True, timeout=10,
                                 creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        found += [Path(out) / name for name in _library_names()]
    return found


def _standard_locations() -> list[Path]:
    patterns: list[str]
    if sys.platform == "win32":
        patterns = [
            r"C:\Program Files\LLVM\bin\libclang.dll",
            r"C:\Program Files\Microsoft Visual Studio\*\*\VC\Tools\Llvm\x64\bin\libclang.dll",
            r"C:\Program Files (x86)\Microsoft Visual Studio\*\*\VC\Tools\Llvm\x64\bin\libclang.dll",
        ]
    elif sys.platform == "darwin":
        patterns = [
            "/opt/homebrew/opt/llvm/lib/libclang.dylib",
            "/opt/homebrew/opt/llvm@*/lib/libclang.dylib",
            "/usr/local/opt/llvm/lib/libclang.dylib",
            "/usr/local/opt/llvm@*/lib/libclang.dylib",
            "/Library/Developer/CommandLineTools/usr/lib/libclang.dylib",
            "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/libclang.dylib",
        ]
    else:
        patterns = [
            "/usr/lib/llvm-*/lib/libclang.so*",
            "/usr/lib/x86_64-linux-gnu/libclang-*.so*",
            "/usr/lib/aarch64-linux-gnu/libclang-*.so*",
            "/usr/lib64/libclang.so*",
            "/usr/lib/libclang.so*",
        ]
    found: list[Path] = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern), key=_version_key, reverse=True)
        found += [Path(m) for m in matches]
    return found


def candidates(configured: str | None = None) -> list[Path]:
    result: list[Path] = []
    env = os.environ.get("CARMA_LIBCLANG")
    if env:
        result.append(Path(env))
    if configured:
        result.append(Path(configured))
    # The standalone distribution carries the same adapter's library and builtin headers.
    bundled = Path(__file__).resolve().parents[2] / "_runtime" / "llvm"
    result += _in_llvm_prefix(bundled)
    llvm_path = os.environ.get("LLVM_PATH")
    if llvm_path:
        result += _in_llvm_prefix(Path(llvm_path))
    result += _llvm_config()
    result += _standard_locations()
    return result


def find_libclang(configured: str | None = None) -> Path:
    for path in candidates(configured):
        if path.is_file():
            return path
    raise LibclangError(
        "libclang not found. Install LLVM 19 or newer, or point to the library with the "
        "CARMA_LIBCLANG environment variable or indexer.libclang in .carma/config.yaml"
    )


_loaded: LibclangInfo | None = None


def _register_extras(lib, ci) -> None:
    """Functions the bindings do not register themselves."""
    lib.clang_getClangVersion.argtypes = []
    lib.clang_getClangVersion.restype = ci._CXString
    lib.clang_getOverriddenCursors.argtypes = [ci.Cursor, ctypes.POINTER(ctypes.POINTER(ci.Cursor)), ctypes.POINTER(ctypes.c_uint)]
    lib.clang_getOverriddenCursors.restype = None
    lib.clang_disposeOverriddenCursors.argtypes = [ctypes.POINTER(ci.Cursor)]
    lib.clang_disposeOverriddenCursors.restype = None
    lib.clang_Cursor_isInlineNamespace.argtypes = [ci.Cursor]
    lib.clang_Cursor_isInlineNamespace.restype = ctypes.c_uint


def load(path: Path) -> LibclangInfo:
    """Load libclang into this process (once; the bindings keep one global library)."""
    global _loaded
    import clang.cindex as ci

    if _loaded is not None:
        if _loaded.path != path:
            raise LibclangError(f"libclang is already loaded from {_loaded.path}")
        return _loaded
    if not ci.Config.loaded:
        ci.Config.set_library_file(str(path))
        ci.Config.set_compatibility_check(False)
    try:
        lib = ci.conf.lib
    except ci.LibclangError as exc:
        raise LibclangError(f"cannot load {path}: {exc}") from exc
    _register_extras(lib, ci)
    version = ci._CXString.from_result(lib.clang_getClangVersion())
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", version)
    number = match.group(0) if match else "0.0.0"
    major = int(match.group(1)) if match else 0
    _loaded = LibclangInfo(path=path, version=version, number=number, major=major)
    return _loaded


def resource_dir(info: LibclangInfo) -> Path | None:
    """clang's builtin headers (stddef.h, intrinsics) of the same LLVM installation.

    libclang is supposed to find them itself, but the official Linux build of LLVM 21 does not,
    so the adapter always passes -resource-dir explicitly when it can find the folder.
    """
    lib_dir = info.path.resolve().parent
    prefix = lib_dir.parent
    for base in (prefix / "lib", prefix / "lib64", lib_dir):
        for version in (str(info.major), info.number):
            folder = base / "clang" / version
            if (folder / "include" / "stddef.h").is_file():
                return folder
    clang = prefix / "bin" / ("clang.exe" if sys.platform == "win32" else "clang")
    if clang.is_file():
        try:
            out = subprocess.run([str(clang), "-print-resource-dir"], capture_output=True, text=True, check=True, timeout=30,
                                 creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        except (OSError, subprocess.SubprocessError):
            return None
        folder = Path(out.stdout.strip())
        if (folder / "include" / "stddef.h").is_file():
            return folder
    return None


_sdk: str | None = None


def macos_sdk() -> str | None:
    """SDK path for the standard headers on macOS; CMake 4 no longer puts -isysroot into commands."""
    global _sdk
    if sys.platform != "darwin":
        return None
    if _sdk is None:
        try:
            _sdk = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True, check=True, timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            _sdk = ""
    return _sdk or None


def version_warning(info: LibclangInfo) -> str | None:
    if "Apple" in info.version:
        return None  # Apple numbers its clang differently; parsing problems show up as diagnostics
    if info.major < MIN_MAJOR:
        return f"{info.version} is older than LLVM {MIN_MAJOR}; C++20 code and new MSVC STL may not parse"
    return None
