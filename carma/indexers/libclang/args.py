"""Turning a compiler command line into arguments for libclang."""

from __future__ import annotations

import os
from pathlib import Path

from carma.compiledb import CompileCommand
from carma.compiledb.shell import split_command
from carma.paths import norm_abs

STL_MISMATCH_DEFINE = "-D_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH"

# Flags that only matter for code generation or build bookkeeping.
_DROP_EXACT = {"-c", "/c", "-S", "/S", "-E", "/E", "--", "/showIncludes", "-showIncludes", "/FS", "-FS", "/Gm", "-Gm", "/Zi", "-Zi", "/ZI", "-ZI", "/Z7", "-Z7"}
_DROP_WITH_VALUE = {"-o", "-include-pch", "-MF", "-MT", "-MQ"}
_DROP_PREFIX_CL = ("/Fo", "-Fo", "/Fd", "-Fd", "/Fp", "-Fp", "/Fe", "-Fe", "/Fa", "-Fa", "/FR", "-FR", "/Fr", "-Fr", "/Yu", "-Yu", "/Yc", "-Yc", "/RTC", "-RTC")
_DROP_GNU_DEPS = {"-M", "-MM", "-MD", "-MMD", "-MP", "-MG"}


def _expand_response_files(args: list[str], directory: Path, windows: bool) -> list[str]:
    result: list[str] = []
    for arg in args:
        if arg.startswith("@") and len(arg) > 1:
            path = Path(arg[1:])
            if not path.is_absolute():
                path = directory / path
            try:
                result += split_command(path.read_text(encoding="utf-8", errors="replace"), windows=windows)
                continue
            except OSError:
                pass
        result.append(arg)
    return result


_SYSROOT_FLAGS = ("-isysroot", "--sysroot", "/winsysroot", "-winsysroot")


def libclang_args(cmd: CompileCommand, *, resource_dir: str | None = None, sysroot: str | None = None) -> list[str]:
    """Arguments for clang_parseTranslationUnit: no compiler name, no source file, no output flags.

    resource_dir points libclang at its builtin headers; sysroot is added only when the
    command has none (macOS SDK).
    """
    cl = cmd.cl_mode
    raw = _expand_response_files(list(cmd.arguments[1:]), cmd.directory, windows=os.name == "nt")
    file_key = norm_abs(cmd.file)
    out: list[str] = []
    i = 0
    while i < len(raw):
        arg = raw[i]
        i += 1
        # the source file itself
        if not arg.startswith("-") and norm_abs(cmd.directory / arg) == file_key:
            continue
        if arg in _DROP_EXACT:
            continue
        if arg in _DROP_WITH_VALUE:
            i += 1
            continue
        if arg == "-Xclang" and raw[i:i + 1] == ["-include-pch"]:
            i += 3  # -Xclang -include-pch -Xclang <file>
            continue
        if not cl and (arg in _DROP_GNU_DEPS or (arg.startswith("-o") and len(arg) > 2)):
            continue
        if cl and arg.startswith(_DROP_PREFIX_CL):
            continue
        out.append(arg)
    if cl and not any(a.startswith("--driver-mode=") for a in out):
        out.insert(0, "--driver-mode=cl")
    if resource_dir:
        out += ["-resource-dir", resource_dir]
    if sysroot and not any(a.startswith(_SYSROOT_FLAGS) for a in out):
        out += ["-isysroot", sysroot]
    return out
