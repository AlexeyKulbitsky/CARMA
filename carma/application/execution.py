"""On-demand, isolated execution analysis with a dependency-aware project cache."""

import hashlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from carma.compiledb.sources import from_cmake_build, from_compile_commands
from carma.config import Config
from carma.execution.api import ExecutionFunction, ExecutionUnavailable, VERSION
from carma.model.json_io import read_json, write_json
from carma.paths import norm_abs


def fingerprint(paths: list[str]) -> dict[str, list[int]]:
    result = {}
    for path in paths:
        try:
            stat = Path(path).stat()
            result[path] = [stat.st_mtime_ns, stat.st_size]
        except OSError:
            result[path] = [-1, -1]
    return result


class ExecutionService:
    def __init__(self, config: Config):
        self.config = config
        self._lock = threading.Lock()

    def function(self, symbol: str, path: str, line: int) -> ExecutionFunction:
        with self._lock:
            root = self.config.project_root
            source = (root / path).resolve()
            if not source.is_relative_to(root) or not source.is_file():
                raise ExecutionUnavailable("The function's source file is unavailable in this project.")
            if self.config.compile_commands:
                commands = from_compile_commands(root / self.config.compile_commands)
            else:
                commands = from_cmake_build(root / self.config.cmake_build_dir, self.config.configuration, reconfigure=False)
            command = next((c for c in commands if norm_abs(c.file) == norm_abs(source)), None)
            if command is None:
                # Header bodies use the nearest TU's include paths and defines; disclose that approximation.
                choices = sorted(commands, key=lambda c: (-len(os.path.commonprefix([str(c.file.parent), str(source.parent)])), str(c.file)))
                command = choices[0] if choices else None
            if command is None:
                raise ExecutionUnavailable("No compilation settings are available. Update this project's map first.")
            signature = hashlib.sha256(json.dumps([VERSION, 5, str(source), str(command.directory), command.arguments,
                                                  self.config.raw], sort_keys=True).encode()).hexdigest()
            directory = self.config.cache_dir / "execution" / signature
            result_path = directory / "analysis.json"
            result = read_json(result_path, {})
            if not result or result.get("fingerprint") != fingerprint(result.get("dependencies", [])):
                directory.mkdir(parents=True, exist_ok=True)
                spec_path = directory / "request.json"
                write_json(spec_path, {"kind": "execution", "root": str(root), "source": str(source),
                                      "directory": str(command.directory), "command_file": str(command.file), "arguments": list(command.arguments),
                                      "output": str(result_path)})
                arguments = [sys.executable, "--worker", str(spec_path)] if getattr(sys, "frozen", False) else [
                    sys.executable, "-m", "carma.application.worker", str(spec_path)]
                environment = os.environ.copy()
                environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2]) + os.pathsep + environment.get("PYTHONPATH", "")
                try:
                    with (directory / "worker.log").open("w", encoding="utf-8") as output:
                        subprocess.run(arguments, cwd=root, env=environment, stdout=output, stderr=output, timeout=90,
                                       creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0, check=True)
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                    result = read_json(directory / "result.json", {})
                    raise ExecutionUnavailable(result.get("error", "Execution analysis could not finish. Check the project's build settings.")) from exc
                result = read_json(result_path, {})
            data = result.get("functions", {}).get(symbol)
            if data is None:
                raise ExecutionUnavailable("No function body was found in the selected build configuration. Try updating the map.")
            flow = ExecutionFunction.model_validate(data)
            if norm_abs(command.file) != norm_abs(source):
                flow.warnings.append("This header was analyzed using compilation settings from " + command.file.name + ".")
            return flow


def run_analysis(spec: dict) -> None:
    from carma.compiledb.model import CompileCommand
    from carma.config import load_config
    from carma.indexers.libclang import discovery
    from carma.indexers.libclang.args import libclang_args
    from carma.indexers.libclang.execution import analyze

    root = Path(spec["root"])
    config = load_config(root)
    library = discovery.find_libclang(config.libclang)
    info = discovery.load(library)
    resource = discovery.resource_dir(info)
    sysroot = discovery.macos_sdk()
    command = CompileCommand(Path(spec["directory"]), Path(spec["command_file"]), tuple(spec["arguments"]))
    args = libclang_args(command, resource_dir=str(resource) if resource else None, sysroot=str(sysroot) if sysroot else None)
    if Path(spec["source"]).suffix.lower() in {".h", ".hpp", ".hh", ".hxx", ".inl"}:
        args += ["-x", "c++"]
    # Only this worker changes cwd; the application and concurrent requests never do.
    os.chdir(command.directory)
    result = analyze(spec["source"], args, str(library), str(root), config.ignore)
    result["dependencies"].extend([str(library), str(config.carma_dir / "config.yaml")])
    result["fingerprint"] = fingerprint(result["dependencies"])
    write_json(Path(spec["output"]), result)
