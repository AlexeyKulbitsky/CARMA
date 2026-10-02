"""Refresh the license texts for the redistributable LLVM/CMake runtime from their upstreams."""

from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    directory = ROOT / "packaging/licenses"
    directory.mkdir(parents=True, exist_ok=True)
    for name, url in {
        "LLVM.txt": "https://raw.githubusercontent.com/llvm/llvm-project/llvmorg-21.1.7/llvm/LICENSE.TXT",
        "CMake.txt": "https://raw.githubusercontent.com/Kitware/CMake/v4.1.0-rc2/LICENSE.rst",
    }.items():
        with urlopen(url, timeout=30) as response:
            (directory / name).write_bytes(response.read())
        print(f"Saved {name}")
