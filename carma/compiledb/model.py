from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

CL_DRIVERS = {"cl", "cl.exe", "clang-cl", "clang-cl.exe"}
SOURCE_EXTENSIONS = {".c", ".cc", ".cpp", ".cxx", ".c++", ".cp", ".m", ".mm"}


class CompileDbError(Exception):
    pass


@dataclass(frozen=True)
class CompileCommand:
    """One translation unit: arguments[0] is the compiler, the source file is among the rest."""

    directory: Path
    file: Path
    arguments: tuple[str, ...]

    @property
    def cl_mode(self) -> bool:
        """True for MSVC-style command lines (cl.exe, clang-cl)."""
        if any(a.startswith("--driver-mode=") for a in self.arguments):
            return any(a == "--driver-mode=cl" for a in self.arguments)
        return os.path.basename(self.arguments[0]).lower() in CL_DRIVERS if self.arguments else False

    @property
    def language(self) -> str:
        return "c" if self.file.suffix.lower() == ".c" else "cpp"
