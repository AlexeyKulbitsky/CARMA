"""Window contract. Native clients may use the same HTTP API without implementing this host."""

from typing import Protocol


class Window(Protocol):
    def choose_folder(self) -> str | None:
        """Choose a local project folder, or return None on cancellation."""
        ...

    def run(self, url: str) -> None:
        """Display the client; flush pending viewing state before returning on close."""
        ...

    def show_error(self, message: str) -> None:
        """Display a startup failure without requiring a terminal."""
        ...
