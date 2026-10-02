"""The current window adapter. Only this module knows pywebview."""

import sys
import threading


class WebviewWindow:
    def __init__(self):
        self.window = None
        self._allow_close = False
        self._closing = False

    def _before_close(self):
        if self._allow_close:
            return True
        if self._closing:
            return False
        self._closing = True

        def finished(result):
            if isinstance(result, dict) and not result.get("ok", False):
                self._closing = False
                if not self.window.create_confirmation_dialog("Could not save your view",
                    "Your latest viewing changes could not be saved. Close without saving them?\n\n" + result.get("message", "")):
                    return
            self._allow_close = True
            self.window.destroy()

        def flush():
            try:
                self.window.evaluate_js("window.carmaPrepareClose ? window.carmaPrepareClose() : Promise.resolve({ok:true})", callback=finished)
            except Exception:
                # A window closed before its page loaded has no viewing state to flush.
                finished({"ok": True})

        # The native closing event runs on the GUI thread. Let it return before invoking JS.
        threading.Thread(target=flush, daemon=True).start()
        return False

    def choose_folder(self) -> str | None:
        import webview
        if self.window is None:
            return None
        paths = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        return paths[0] if paths else None

    def run(self, url: str) -> None:
        import webview
        self.window = webview.create_window("CARMA", url, width=1440, height=900, min_size=(800, 600), text_select=True)
        self.window.events.closing += self._before_close
        # Use a modern renderer. Falling back to Internet Explorer would silently break the map.
        webview.start(gui="edgechromium" if sys.platform == "win32" else None, private_mode=True)

    def show_error(self, message: str) -> None:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "CARMA", 0x10)
        else:
            from tkinter import Tk, messagebox
            root = Tk()
            root.withdraw()
            messagebox.showerror("CARMA", message)
            root.destroy()
