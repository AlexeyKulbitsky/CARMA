from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from carma.compiledb.model import CL_DRIVERS, SOURCE_EXTENSIONS, CompileCommand, CompileDbError
from carma.compiledb.shell import split_command
from carma.paths import norm_abs

QUERY_CLIENT = "client-carma"
QUERY = {"requests": [{"kind": "codemodel", "version": 2}, {"kind": "toolchains", "version": 1}]}


def _dedupe(commands: list[CompileCommand]) -> list[CompileCommand]:
    """Keep the first command for every source file (a file can be built by several targets)."""
    seen: set[str] = set()
    result = []
    for cmd in commands:
        key = norm_abs(cmd.file)
        if key not in seen:
            seen.add(key)
            result.append(cmd)
    return result


# ---------------------------------------------------------------- compile_commands.json


def from_compile_commands(path: Path) -> list[CompileCommand]:
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CompileDbError(f"cannot read {path}: {exc}") from exc
    commands = []
    for entry in entries:
        directory = Path(entry["directory"])
        if "arguments" in entry:
            arguments = list(entry["arguments"])
        else:
            arguments = split_command(entry["command"])
        file = Path(entry["file"])
        if not file.is_absolute():
            file = directory / file
        commands.append(CompileCommand(directory=directory, file=Path(os.path.normpath(file)), arguments=tuple(arguments)))
    return _dedupe(commands)


# ---------------------------------------------------------------- CMake File API


def write_query(build_dir: Path) -> None:
    query_dir = build_dir / ".cmake" / "api" / "v1" / "query" / QUERY_CLIENT
    query_dir.mkdir(parents=True, exist_ok=True)
    (query_dir / "query.json").write_text(json.dumps(QUERY), encoding="utf-8")


def run_cmake(build_dir: Path) -> None:
    """Re-run configuration of an existing build folder so CMake writes the File API reply."""
    cmake = shutil.which("cmake")
    if cmake is None:
        raise CompileDbError("cmake is not on PATH; it is needed to read a CMake build folder")
    if not (build_dir / "CMakeCache.txt").is_file():
        raise CompileDbError(
            f"{build_dir} is not a configured CMake build folder; configure it first, e.g. cmake -S . -B {build_dir.name}"
        )
    result = subprocess.run([cmake, str(build_dir)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise CompileDbError(f"cmake failed in {build_dir}:\n{result.stdout}\n{result.stderr}")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _reply(build_dir: Path) -> tuple[Path, dict, dict]:
    reply_dir = build_dir / ".cmake" / "api" / "v1" / "reply"
    indexes = sorted(reply_dir.glob("index-*.json"))
    if not indexes:
        raise CompileDbError(f"no CMake File API reply in {reply_dir}")
    index = _read_json(indexes[-1])
    try:
        responses = index["reply"][QUERY_CLIENT]["query.json"]["responses"]
    except KeyError as exc:
        raise CompileDbError(f"the CMake File API reply has no answer for {QUERY_CLIENT}") from exc
    by_kind = {}
    for response in responses:
        if "error" in response:
            raise CompileDbError(f"CMake File API error: {response['error']}")
        by_kind[response["kind"]] = _read_json(reply_dir / response["jsonFile"])
    if "codemodel" not in by_kind:
        raise CompileDbError("the CMake File API reply has no codemodel")
    return reply_dir, by_kind["codemodel"], by_kind.get("toolchains", {"toolchains": []})


def _pick_configuration(codemodel: dict, wanted: str | None) -> dict:
    configurations = codemodel["configurations"]
    names = [c["name"] for c in configurations]
    if len(configurations) == 1:
        return configurations[0]  # single-config generators (Makefiles, Ninja): the setting does not apply
    if wanted:
        for c in configurations:
            if c["name"] == wanted:
                return c
        raise CompileDbError(f"configuration {wanted!r} not found; available: {names}")
    for c in configurations:
        if c["name"] == "Debug":
            return c
    return configurations[0]


def _flag_style(compiler: str) -> str:
    return "cl" if os.path.basename(compiler).lower() in CL_DRIVERS else "gnu"


def _group_arguments(group: dict, compiler: str, windows_shell: bool) -> list[str]:
    style = _flag_style(compiler)
    args: list[str] = [compiler]
    for fragment in group.get("compileCommandFragments", []):
        args += split_command(fragment["fragment"], windows=windows_shell)
    for include in group.get("includes", []):
        path = include["path"]
        if style == "cl":
            args.append(("/imsvc" if include.get("isSystem") else "/I") + path)
        elif include.get("isSystem"):
            args += ["-isystem", path]
        else:
            args.append("-I" + path)
    for framework in group.get("frameworks", []):
        args.append(("-iframework" if framework.get("isSystem") else "-F") + framework["path"])
    for define in group.get("defines", []):
        args.append(("/D" if style == "cl" else "-D") + define["define"])
    standard = (group.get("languageStandard") or {}).get("standard")
    if standard and not any(a.startswith(("-std", "/std")) for a in args):
        lang = "c++" if group.get("language") == "CXX" else "c"
        if style == "cl":
            value = f"c++{standard}" if lang == "c++" and standard in ("14", "17", "20") else "c++latest" if lang == "c++" else f"c{standard}"
            args.append(f"/std:{value}")
        else:
            args.append(f"-std={lang}{standard}")
    sysroot = (group.get("sysroot") or {}).get("path")
    if sysroot:
        args += ["-isysroot", sysroot]
    return args


def from_cmake_build(build_dir: Path, configuration: str | None = None, *, reconfigure: bool = True) -> list[CompileCommand]:
    """Compile commands of a configured CMake build folder, for any generator (VS, Xcode, Ninja, Makefiles)."""
    build_dir = build_dir.resolve()
    write_query(build_dir)
    if reconfigure:
        run_cmake(build_dir)
    reply_dir, codemodel, toolchains = _reply(build_dir)
    compilers = {t["language"]: t["compiler"].get("path") for t in toolchains.get("toolchains", []) if "compiler" in t}
    source_root = Path(codemodel["paths"]["source"])
    config = _pick_configuration(codemodel, configuration)
    windows_shell = os.name == "nt"

    commands: list[CompileCommand] = []
    for target_ref in config["targets"]:
        target = _read_json(reply_dir / target_ref["jsonFile"])
        groups = target.get("compileGroups", [])
        target_build = build_dir / target.get("paths", {}).get("build", ".")
        for source in target.get("sources", []):
            index = source.get("compileGroupIndex")
            if index is None:
                continue
            group = groups[index]
            compiler = compilers.get(group.get("language", ""))
            if not compiler:
                continue
            file = Path(source["path"])
            if not file.is_absolute():
                file = source_root / file
            if file.suffix.lower() not in SOURCE_EXTENSIONS:
                continue
            file = Path(os.path.normpath(file))
            arguments = _group_arguments(group, compiler, windows_shell) + ["-c", str(file)]
            commands.append(CompileCommand(directory=target_build, file=file, arguments=tuple(arguments)))
    return _dedupe(commands)


def load_for_config(config) -> list[CompileCommand]:
    """Compile commands for a carma Config: compile_commands.json or a CMake build folder."""
    if config.compile_commands:
        return from_compile_commands(config.project_root / config.compile_commands)
    if config.cmake_build_dir:
        return from_cmake_build(config.project_root / config.cmake_build_dir, config.configuration)
    raise CompileDbError("config has no compile_db source")
