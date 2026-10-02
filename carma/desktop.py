"""Composition root: choose a window adapter and connect it to the application service."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def configure_bundled_tools() -> None:
    """Ship the indexer and CMake with the app, without changing the user's system settings."""
    runtime = Path(__file__).resolve().parent / "_runtime"
    tools = [runtime / "cmake/bin", runtime / "llvm/bin"]
    if any(p.is_dir() for p in tools):
        os.environ["PATH"] = os.pathsep.join(str(p) for p in tools if p.is_dir()) + os.pathsep + os.environ.get("PATH", "")
    # External CMake/compiler processes must use system libraries, not the packager's DLL search path.
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        elif "LD_LIBRARY_PATH_ORIG" in os.environ:
            os.environ["LD_LIBRARY_PATH"] = os.environ["LD_LIBRARY_PATH_ORIG"]
        else:
            os.environ.pop("LD_LIBRARY_PATH", None)


def main(window=None) -> int:
    import multiprocessing
    multiprocessing.freeze_support()
    configure_bundled_tools()
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        from carma.application.worker import run
        return run(Path(sys.argv[2]))
    from carma.application.host import ApplicationHost
    from carma.application.manager import ProjectManager, data_directory
    from carma.presentation.webview import WebviewWindow

    window = window or WebviewWindow()
    host = None
    try:
        directory = data_directory()
        directory.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=directory / "application.log", encoding="utf-8", level=logging.WARNING)
        manager = ProjectManager(directory)
        host = ApplicationHost(manager, window.choose_folder)
        host.start()
        window.run(host.url)
        return 0
    except Exception as exc:
        logging.exception("Application failed")
        window.show_error(f"CARMA could not start.\n\n{exc}")
        return 1
    finally:
        if host:
            host.close()


if __name__ == "__main__":
    raise SystemExit(main())
