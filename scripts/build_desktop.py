"""Build a portable native application on the current OS; run after building ui/.

Python, the UI, libclang and its builtin headers are bundled. The project's own SDK
remains a project requirement. No executable or data is installed globally.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from carma.indexers.libclang import discovery
    if not (ROOT / "carma/_ui/index.html").is_file():
        raise RuntimeError("Build ui/ before packaging the desktop application.")
    lib = discovery.find_libclang()
    info = discovery.load(lib)
    headers = discovery.resource_dir(info)
    if headers is None:
        raise RuntimeError("LLVM's builtin headers are required for a standalone build.")
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--onedir", "--name", "CARMA",
               "--specpath", str(ROOT / "build/desktop"), "--workpath", str(ROOT / "build/desktop/work"),
               "--distpath", str(ROOT / "dist"), "--paths", str(ROOT),
               "--add-data", f"{ROOT / 'contracts'}:carma/_contracts",
               "--add-data", f"{ROOT / 'carma/_ui'}:carma/_ui",
               "--add-binary", f"{lib}:carma/_runtime/llvm/{'bin' if sys.platform == 'win32' else 'lib'}",
               "--add-data", f"{headers}:carma/_runtime/llvm/lib/clang/{info.major}",
               "--collect-submodules", "carma", "--collect-all", "webview",
               "--copy-metadata", "carma", "--add-data", f"{ROOT / 'LICENSE'}:."]
    # Include CMake and its modules when installed, so a fresh project needs only its C++ SDK.
    cmake = shutil.which("cmake")
    if cmake:
        executable = Path(cmake).resolve()
        prefix = executable.parent.parent
        modules = sorted((prefix / "share").glob("cmake-*"))
        if modules:
            command.extend(["--add-binary", f"{executable}:carma/_runtime/cmake/bin"])
            command.extend(["--add-data", f"{modules[-1]}:carma/_runtime/cmake/share/{modules[-1].name}"])
        else:
            raise RuntimeError("The CMake modules were not found beside its executable.")
    else:
        raise RuntimeError("CMake is required to build the standalone application.")
    licenses = ROOT / "packaging/licenses"
    if not all((licenses / name).is_file() for name in ("LLVM.txt", "CMake.txt")):
        raise RuntimeError("Runtime licenses are missing. Run scripts/fetch_runtime_licenses.py first.")
    command.extend(["--add-data", f"{licenses}:THIRD_PARTY_LICENSES/runtime"])
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        command.extend(["--add-data", f"{python_license}:THIRD_PARTY_LICENSES/python"])
    for distribution in metadata.distributions():
        for file in distribution.files or ():
            if ".dist-info" not in str(file) or not any(word in str(file).lower() for word in ("license", "copying", "notice")):
                continue
            source = distribution.locate_file(file)
            if source.is_file():
                destination = "THIRD_PARTY_LICENSES/" + distribution.metadata["Name"] + "/" + str(file.parent).replace("\\", "/")
                command.extend(["--add-data", f"{source}:{destination}"])
    # Redistributed third-party licenses travel with the runtime.
    llvm_prefix = lib.parent.parent
    for license_file in (llvm_prefix / "LICENSE.TXT", llvm_prefix / "LICENSE.txt"):
        if license_file.exists():
            command.extend(["--add-data", f"{license_file}:carma/_runtime/llvm"])
            break
    command.append(str(ROOT / "scripts/desktop_entry.py"))
    subprocess.run(command, cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
