"""Native WebView2 integration check: choose a fresh project, render it, reopen and restore.

Uses a hidden window and a deterministic folder picker so it never interrupts the user.
"""

import json
import os
import shutil
import sys
import time
import traceback
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    directory = ROOT / ".cache" / ("window-check-" + uuid.uuid4().hex[:8])
    project = directory / "golden"
    shutil.copytree(ROOT / "fixtures/golden_cpp", project)
    os.environ["CARMA_DATA_DIR"] = str(directory / "settings")
    from carma.desktop import main as start
    from carma.presentation.webview import WebviewWindow
    outcome = {}

    class CheckWindow(WebviewWindow):
        def choose_folder(self):
            return str(project)

        def run(self, url):
            import webview
            self.window = webview.create_window("CARMA integration check", url, width=1440, height=900, hidden=True)
            self.window.events.closing += self._before_close

            def wait_for(expression, timeout=40):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if self.window.evaluate_js(expression):
                        return
                    time.sleep(.1)
                raise AssertionError(self.window.evaluate_js("document.body.innerText"))

            def click(label):
                self.window.evaluate_js("Array.from(document.querySelectorAll('button')).find(b => b.textContent === "
                                        + json.dumps(label) + ").click()")

            def saved_view():
                deadline = time.monotonic() + 10
                path = project / ".carma/workspace.json"
                while time.monotonic() < deadline:
                    if path.exists():
                        data = json.loads(path.read_text(encoding="utf-8"))
                        view = data["views"].get(data["scope"], {})
                        if view.get("metric") == "calls" and view.get("camera"):
                            return data
                    time.sleep(.1)
                raise AssertionError("Viewing state was not saved")

            def exercise():
                try:
                    wait_for("document.querySelector('.open-project') && !document.querySelector('.open-project').disabled")
                    click("Open project folder…")
                    wait_for("Array.from(document.querySelectorAll('button')).some(b => b.textContent === 'Build map')")
                    click("Build map")
                    wait_for("Array.from(document.querySelectorAll('button')).some(b => b.textContent === 'Architecture')", 70)
                    click("Architecture")
                    wait_for("document.querySelector('[aria-label=\"Architecture map\"] .react-flow__node')", 70)
                    assert not self.window.evaluate_js("document.querySelector('.banner-error')?.textContent")
                    # Navigate through the real application controls, then close/reopen the project.
                    node = self.window.evaluate_js("document.querySelector('.react-flow__node').getAttribute('data-id')")
                    self.window.evaluate_js("var n=document.querySelector('.react-flow__node');var r=n.getBoundingClientRect();n.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:r.left+20,clientY:r.top+20}));")
                    wait_for("document.querySelector('[role=menu][aria-label=\"Block actions\"]')")
                    click("Show block details")
                    wait_for("document.querySelector('[id=\"map-details\"]')")
                    self.window.evaluate_js("document.querySelector('.react-flow__node').dispatchEvent(new MouseEvent('dblclick', {bubbles:true}))")
                    wait_for("document.querySelector('.react-flow__node') && window.location.hash !== '#/'")
                    time.sleep(.4)
                    click("calls")
                    self.window.evaluate_js("var p=document.querySelector('.react-flow__pane');var r=p.getBoundingClientRect();p.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:r.left+80,clientY:r.top+80}));")
                    wait_for("document.querySelector('[role=menu][aria-label=\"Canvas actions\"]')")
                    click("Fit map")
                    self.window.evaluate_js("document.querySelector('.react-flow__node').dispatchEvent(new MouseEvent('click', {bubbles:true}))")
                    wait_for("document.querySelector('.position-controls')")
                    click("Move right")
                    self.window.evaluate_js("document.querySelector('.react-flow__controls-zoomin').click()")
                    time.sleep(.8)
                    before = saved_view()
                    pins = json.loads((project / ".carma/layout.json").read_text(encoding="utf-8"))
                    assert before["views"][before["scope"]]["metric"] == "calls", before
                    assert before["views"][before["scope"]]["camera"] is not None, before
                    click("Projects")
                    wait_for("document.querySelector('.recent-projects button')")
                    click("Open")
                    wait_for("document.querySelectorAll('.react-flow__node').length > 0")
                    assert not self.window.evaluate_js("document.querySelector('.banner-error')?.textContent")
                    time.sleep(.6)
                    after = json.loads((project / ".carma/workspace.json").read_text(encoding="utf-8"))
                    assert before == after, (before, after)
                    assert pins == json.loads((project / ".carma/layout.json").read_text(encoding="utf-8"))
                    outcome.update(ok=True, nodes=self.window.evaluate_js("document.querySelectorAll('.react-flow__node').length"),
                                   text=self.window.evaluate_js("document.body.innerText"))
                    # Exit immediately after a filter change; the window must flush the debounce.
                    click("uses")
                except Exception:
                    outcome.update(ok=False, error=traceback.format_exc(), text=self.window.evaluate_js("document.body.innerText"))
                finally:
                    (directory / "result.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
                    self.window.destroy()
            webview.start(exercise, gui="edgechromium")

        def show_error(self, message):
            raise RuntimeError(message)

    assert start(CheckWindow()) == 0
    assert outcome.get("ok"), outcome
    workspace = json.loads((project / ".carma/workspace.json").read_text(encoding="utf-8"))
    assert workspace["views"][workspace["scope"]]["metric"] == "uses", workspace
    print(f"Native window rendered and reopened the project ({outcome['nodes']} visible nodes).")
    print(f"Evidence: {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
