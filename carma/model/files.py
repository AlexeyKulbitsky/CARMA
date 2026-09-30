"""Atomic writes for files under .carma/: a temporary file next to the target, then a rename."""

from __future__ import annotations

import os
from pathlib import Path


def newline_of(path: Path) -> str:
    """The line ending an existing file uses, so a rewrite does not turn the whole file into a diff."""
    try:
        return "\r\n" if b"\r\n" in path.read_bytes() else "\n"
    except FileNotFoundError:
        return "\n"


def write_atomic(path: Path, text: str, newline: str = "\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline=newline) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
