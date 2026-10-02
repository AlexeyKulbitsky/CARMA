"""Exercise the packaged indexer on a fresh project without Python/LLVM/CMake on PATH."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if sys.platform != "win32":
        raise RuntimeError("This packaged executable check targets Windows.")
    executable = ROOT / "dist/CARMA/CARMA.exe"
    directory = ROOT / ".cache" / ("packaged-check-" + __import__("uuid").uuid4().hex[:8])
    project = directory / "golden"
    shutil.copytree(ROOT / "fixtures/golden_cpp", project)
    task = directory / "task"
    task.mkdir()
    staging = project / ".carma/cache/tasks/check/facts.db"
    spec = {"root": str(project), "staging": str(staging), "reindex": False,
            "choice": {"id": "automatic", "kind": "cmake", "path": ".carma/cache/build", "configuration": "Debug"}}
    spec_file = task / "spec.json"
    spec_file.write_text(json.dumps(spec), encoding="utf-8")
    environment = os.environ.copy()
    for key in ("CARMA_LIBCLANG", "LLVM_PATH", "PYTHONPATH"):
        environment.pop(key, None)
    environment["PATH"] = os.pathsep.join([str(Path(os.environ["WINDIR"]) / "System32"), os.environ["WINDIR"]])
    with (task / "worker.log").open("w", encoding="utf-8") as log:
        result = subprocess.run([str(executable), "--worker", str(spec_file)], env=environment,
                                stdout=log, stderr=log, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
    data = json.loads((task / "result.json").read_text(encoding="utf-8"))
    assert result.returncode == 0 and data["ok"], data
    assert staging.is_file() and list((staging.parent / "model").glob("*.yaml"))
    print("Packaged application prepared and indexed a fresh CMake project using only its bundled tools.")
    print(f"Evidence: {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
