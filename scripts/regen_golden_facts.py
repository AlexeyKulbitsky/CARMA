"""Regenerate fixtures/golden_cpp/facts.jsonl, the fact stream the store and core tests load.

Needs CMake and LLVM. Run after changing the fixture or the adapter:

    uv run python scripts/regen_golden_facts.py

The stream is adapter output, not an answer key: correctness is checked against the
hand-written fixtures/golden_cpp/expected/ by tests/contract/test_facts_adapter.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GOLDEN = REPO / "fixtures" / "golden_cpp"


def main() -> int:
    sys.path.insert(0, str(REPO))
    from carma.compiledb import from_cmake_build
    from carma.config import DEFAULT_IGNORE
    from carma.indexers.libclang import discovery
    from carma.indexers.libclang.indexer import index_project, select_tus

    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp) / "build"
        subprocess.run(["cmake", "-S", str(GOLDEN), "-B", str(build)], check=True, capture_output=True)
        tus, _ = select_tus(from_cmake_build(build), GOLDEN, DEFAULT_IGNORE, False)
        raw = Path(tmp) / "facts.jsonl"
        report = index_project(GOLDEN, tus, raw, libclang=discovery.find_libclang(), ignore=DEFAULT_IGNORE)
        lines = raw.read_text(encoding="utf-8").splitlines()

    header = json.loads(lines[0])
    header["project_root"] = "fixtures/golden_cpp"  # no machine-specific absolute path in the repo
    lines[0] = json.dumps(header, ensure_ascii=False, separators=(",", ":"))
    (GOLDEN / "facts.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {GOLDEN / 'facts.jsonl'}: {report.symbols} symbols, {report.refs} refs, "
          f"{report.relations} relations ({header['platform']}, clang {header['indexer']['clang']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
