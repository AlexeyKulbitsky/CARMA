"""Text helpers for canonical IDs (see the spec, «Канонические идентификаторы»).

These do not touch libclang, so they are unit-tested on their own.
"""

from __future__ import annotations

import re

SCHEME = "cxx "
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def escape(name: str) -> str:
    """Names that are not identifiers (operators, paths) go in backticks, as in SCIP."""
    if _IDENT.match(name):
        return name
    return "`" + name.replace("`", "``") + "`"


_CALLING_CONVENTION = re.compile(r"\b__(?:cdecl|stdcall|fastcall|vectorcall|thiscall|clrcall|regcall)\b")


def _strip_attributes(text: str) -> str:
    """Drop `__attribute__((...))` groups; clang prints calling conventions this way on some platforms."""
    out = []
    i = 0
    while True:
        start = text.find("__attribute__((", i)
        if start < 0:
            out.append(text[i:])
            return "".join(out)
        out.append(text[i:start])
        depth = 0
        j = start + len("__attribute__")
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            j += 1
        i = j


def norm_type(text: str) -> str:
    """Written type with normalized spaces: `const std::string &` -> `const std::string&`.

    Calling-convention attributes are dropped: they differ between platforms, the code does not.
    """
    text = _CALLING_CONVENTION.sub(" ", _strip_attributes(text))
    text = " ".join(text.split())
    text = re.sub(r"\s+([*&,()\[\]>])", r"\1", text)
    text = re.sub(r"([(<\[])\s+", r"\1", text)
    text = re.sub(r",(?=\S)", ", ", text)
    return text


def file_segment(path: str) -> str:
    return escape(path) + "/"
