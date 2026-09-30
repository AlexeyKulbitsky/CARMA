"""Project-relative paths and glob matching shared by the indexer and the core.

Paths in facts, the model and the API are relative to the project root and use '/'.
On Windows, comparisons ignore case.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path, PurePosixPath

CASE_INSENSITIVE = os.name == "nt"


def norm_abs(path: str | os.PathLike[str]) -> str:
    """Absolute, normalized path string used as a comparison key."""
    text = os.path.normpath(os.path.abspath(os.fspath(path)))
    return text.casefold() if CASE_INSENSITIVE else text


def relpath(path: str | os.PathLike[str], root: Path) -> str | None:
    """Path relative to root with '/' separators, or None when it lies outside root."""
    absolute = os.path.normpath(os.path.abspath(os.fspath(path)))
    root_text = os.path.normpath(os.path.abspath(root))
    try:
        rel = os.path.relpath(absolute, root_text)
    except ValueError:  # different drive on Windows
        return None
    if rel == os.curdir or rel.startswith(os.pardir + os.sep) or rel == os.pardir or os.path.isabs(rel):
        return None
    return PurePosixPath(*Path(rel).parts).as_posix()


@lru_cache(maxsize=1024)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    """gitignore-like globs: '**/' matches zero or more folders, '*' and '?' stay within one segment."""
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("/**", i) and i + 3 == len(pattern):
            out.append("(?:/.*)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    flags = re.IGNORECASE if CASE_INSENSITIVE else 0
    return re.compile("".join(out), flags)


def glob_match(path: str, pattern: str) -> bool:
    return _glob_regex(pattern).fullmatch(path) is not None


def matches_any(path: str, patterns: list[str] | tuple[str, ...]) -> bool:
    return any(glob_match(path, p) for p in patterns)
