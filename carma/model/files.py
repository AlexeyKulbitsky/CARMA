"""Atomic writes for files under .carma/: a temporary file next to the target, then a rename."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path


def newline_of(path: Path) -> str:
    """The line ending an existing file uses, so a rewrite does not turn the whole file into a diff."""
    try:
        return "\r\n" if b"\r\n" in path.read_bytes() else "\n"
    except FileNotFoundError:
        return "\n"


def write_atomic(path: Path, text: str, newline: str = "\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline=newline, delete=False,
                                         dir=path.parent, prefix=f".{path.name}.", suffix=".tmp") as f:
            tmp = Path(f.name)
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                break
            except PermissionError as exc:
                # A concurrent Windows reader briefly holds the old file without delete sharing.
                if os.name != "nt" or getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 19:
                    raise
                time.sleep(.01)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
