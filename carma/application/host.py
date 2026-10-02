"""Local API lifetime, independent of the window implementation."""

import socket
import threading
import time

import uvicorn

from carma.api.app import create_app
from carma.application.manager import ProjectManager


class ApplicationHost:
    def __init__(self, manager: ProjectManager, choose_folder):
        self.manager = manager
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self.socket.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(create_app(manager=manager, choose_folder=choose_folder),
                                                  log_config=None, access_log=False, timeout_graceful_shutdown=2))
        self.thread = threading.Thread(target=lambda: self.server.run(sockets=[self.socket]), daemon=True)

    def start(self) -> None:
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError("CARMA could not start its local service.")
            time.sleep(0.02)

    def close(self) -> None:
        self.manager.shutdown()
        self.server.should_exit = True
        if self.thread.is_alive():
            self.thread.join(timeout=10)
        self.socket.close()
