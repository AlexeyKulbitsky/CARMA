"""Splitting command strings the way the compiler's shell would."""

from __future__ import annotations

import os
import shlex


def split_windows(command: str) -> list[str]:
    """Split like CommandLineToArgvW: quotes group, backslashes escape only before a quote."""
    args: list[str] = []
    current: list[str] = []
    in_quotes = False
    has_token = False
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if ch == "\\":
            backslashes = 0
            while i < n and command[i] == "\\":
                backslashes += 1
                i += 1
            if i < n and command[i] == '"':
                current.append("\\" * (backslashes // 2))
                if backslashes % 2:
                    current.append('"')
                    i += 1
                has_token = True
            else:
                current.append("\\" * backslashes)
                has_token = True
            continue
        if ch == '"':
            if in_quotes and i + 1 < n and command[i + 1] == '"':
                current.append('"')  # "" inside quotes is a literal quote
                i += 2
                continue
            in_quotes = not in_quotes
            has_token = True
            i += 1
            continue
        if ch in " \t" and not in_quotes:
            if has_token:
                args.append("".join(current))
                current = []
                has_token = False
            i += 1
            continue
        current.append(ch)
        has_token = True
        i += 1
    if has_token:
        args.append("".join(current))
    return args


def split_command(command: str, windows: bool | None = None) -> list[str]:
    if windows is None:
        windows = os.name == "nt"
    return split_windows(command) if windows else shlex.split(command)
