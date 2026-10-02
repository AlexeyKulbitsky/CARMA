"""Isolated project preparation. Killing this process leaves the published fact database intact."""

import traceback
from pathlib import Path

from carma.application.files import read_json, write_json
from carma.application.preparation import prepare


def run(spec_path: Path) -> int:
    spec = read_json(spec_path)
    progress_path = spec_path.parent / "progress.json"

    def progress(stage, message, done=0, total=0):
        write_json(progress_path, {"stage": stage, "message": message, "done": done, "total": total})

    try:
        warnings = prepare(Path(spec["root"]), spec["choice"], Path(spec["staging"]), progress, reindex=spec["reindex"])
        write_json(spec_path.parent / "result.json", {"ok": True, "warnings": warnings})
        return 0
    except Exception as exc:
        traceback.print_exc()
        write_json(spec_path.parent / "result.json", {"ok": False, "error": str(exc), "code": getattr(exc, "code", "project_error")})
        return 1


if __name__ == "__main__":
    import multiprocessing
    import sys
    multiprocessing.freeze_support()
    raise SystemExit(run(Path(sys.argv[1])))
