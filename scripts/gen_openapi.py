"""Regenerate contracts/openapi.yaml, contract 4, from the View API routes.

Run after changing carma/api/:

    uv run python scripts/gen_openapi.py

The file is committed; tests/contract/test_view_api.py fails when it differs from the code.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    sys.path.insert(0, str(REPO))
    from carma.api.app import openapi_yaml

    path = REPO / "contracts" / "openapi.yaml"
    path.write_text(openapi_yaml(), encoding="utf-8", newline="\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
