"""Native window check: expand a contextual virtual call, inspect a type and reopen the exploration."""

import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SOURCE = """\
struct Renderer { virtual void Render() {} };
struct ForwardRenderer : Renderer { void Render() override {} };
struct Application { virtual bool Init() { return true; } virtual void Update() {} virtual void Destroy() {} };
struct Game : Application {
    ForwardRenderer* renderer;
    int score = 0;
    void SetRenderer(ForwardRenderer* value) { renderer = value; }
    bool Init() override { score = 1; return true; }
    void Update() override { ++score; }
};
struct Engine {
    Application* application;
    Renderer* renderer;
    static Engine& GetInstance() { static Engine instance; return instance; }
    void SetApplication(Application* value) { application = value; }
    void SetRenderer(Renderer* value) { renderer = value; }
    bool Init() {
        // Window settings
        Hint(1); Hint(2); Hint(3);
        // Application initialization
        if (!application) { return false; }
        return application->Init();
    }
    void Hint(int value) {}
    void Run() { for (int frame = 0; frame < 2; ++frame) { application->Update(); renderer->Render(); } }
    void Destroy() { application->Destroy(); delete application; delete renderer; }
};
int main() {
    Engine& engine = Engine::GetInstance();
    auto* game = new Game();
    engine.SetApplication(game);
    auto* renderer = new ForwardRenderer();
    game->SetRenderer(renderer);
    engine.SetRenderer(renderer);
    if (!engine.Init()) { return -1; }
    engine.Run();
    engine.Destroy();
    return 0;
}
"""


def main() -> int:
    directory = ROOT / ".cache" / ("execution-window-" + uuid.uuid4().hex[:8])
    project = directory / "project"
    project.mkdir(parents=True)
    (project / "main.cpp").write_text(SOURCE, encoding="utf-8")
    (project / "CMakeLists.txt").write_text('cmake_minimum_required(VERSION 3.20)\nproject(Flow LANGUAGES CXX)\nadd_executable(Flow main.cpp)\n', encoding="utf-8")
    os.environ["CARMA_DATA_DIR"] = str(directory / "settings")
    from carma.desktop import main as start
    from carma.presentation.webview import WebviewWindow
    outcome = {}

    class CheckWindow(WebviewWindow):
        def choose_folder(self):
            return str(project)

        def run(self, url):
            import webview
            self.window = webview.create_window("CARMA execution check", url, width=1440, height=900, hidden=True)
            self.window.events.closing += self._before_close

            def wait_for(expression, timeout=60):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if self.window.evaluate_js("Boolean(" + expression + ")"):
                        return
                    time.sleep(.1)
                raise AssertionError(self.window.evaluate_js("document.body.innerText"))

            def click(label):
                expression = "Array.from(document.querySelectorAll('button')).find(b => b.textContent === " + json.dumps(label) + ")"
                wait_for(expression)
                self.window.evaluate_js(expression + ".click()")

            def saved():
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    path = project / ".carma/exploration.json"
                    if path.exists():
                        data = json.loads(path.read_text(encoding="utf-8"))
                        view = next(iter(data.get("views", {}).values()), {})
                        if len(view.get("expanded", {})) == 2 and view.get("positions") and data.get("studies"):
                            return data
                    time.sleep(.1)
                raise AssertionError("Exploration was not saved")

            def exercise():
                try:
                    click("Open project folder…")
                    click("Build map")
                    wait_for("document.querySelector('.execution-card') && document.querySelector('.execution-step-list')")
                    click("if (!engine.Init())")
                    # Keep the caller at exactly the same position while opening its body.
                    wait_for("document.querySelector('.react-flow__node.selected')")
                    caller_id = self.window.evaluate_js("document.querySelector('.react-flow__node.selected').getAttribute('data-id')")
                    deadline = time.monotonic() + 10
                    while not (project / ".carma/exploration.json").exists() and time.monotonic() < deadline:
                        time.sleep(.1)
                    initial = json.loads((project / ".carma/exploration.json").read_text(encoding="utf-8"))
                    caller_position = next(iter(initial["views"].values()))["positions"][caller_id]
                    click("Expand Engine::Init().")
                    wait_for("document.body.innerText.includes('Steps in Init()')")
                    click("Window settings")
                    click("Expand block")
                    wait_for("document.body.innerText.includes('Hint(1)')")
                    # Group the three settings through the same controls used by a person.
                    self.window.evaluate_js("Array.from(document.querySelectorAll('.execution-step-list input[type=checkbox]')).slice(0,3).forEach(e => e.click())")
                    self.window.evaluate_js("var e=document.querySelector('[aria-label=\"New group name\"]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,'GLFW Init'); e.dispatchEvent(new Event('input',{bubbles:true}));")
                    click("Group selected blocks")
                    wait_for("document.body.innerText.includes('GLFW Init')")
                    wait_for("document.querySelector('[aria-label=\"Study status\"]')")
                    self.window.evaluate_js("var e=document.querySelector('[aria-label=\"Study status\"]'); e.value='understood'; e.dispatchEvent(new Event('change',{bubbles:true}));")
                    self.window.evaluate_js("var e=document.querySelector('[aria-label=\"Study note\"]'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(e,'Window context settings'); e.dispatchEvent(new Event('input',{bubbles:true}));")
                    self.window.evaluate_js("document.querySelector('[aria-label=\"Use color #438a60\"]').click()")
                    click("Open separately")
                    wait_for("document.body.innerText.includes('Click a free spot')")
                    self.window.evaluate_js("var e=document.querySelector('.react-flow__pane');var r=e.getBoundingClientRect();e.dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:r.left+100,clientY:r.top+150}));")
                    wait_for("document.querySelector('.inspection-frame')")
                    # Both the separate copy and the original share the same annotation.
                    click("Init()")
                    click("Application initialization")
                    click("Expand block")
                    click("return application->Init()")
                    wait_for("document.body.innerText.includes('Receiver type inferred')")
                    click("Expand Game::Init().")
                    wait_for("document.body.innerText.includes('score = 1')")
                    click("Move step right")
                    self.window.evaluate_js("document.querySelector('.react-flow__controls-zoomin').click()")
                    time.sleep(.5)
                    before = saved()
                    assert next(iter(before["views"].values()))["positions"][caller_id] == caller_position
                    studies = list(before["studies"].values())
                    assert any(any(a.get("note") == "Window context settings" and a.get("status") == "understood" for a in s.get("annotations", {}).values()) for s in studies)
                    assert any(v.get("detached") for v in before["views"].values())
                    click("← Exploration overview")
                    click("Game")
                    wait_for("document.body.innerText.toLowerCase().includes('base types') && document.body.innerText.includes('score')")
                    assert not self.window.evaluate_js("document.querySelector('.banner-error')?.textContent")
                    click("Projects")
                    click("Open")
                    wait_for("document.querySelector('.execution-card') && document.body.innerText.toLowerCase().includes('expanded functions')")
                    time.sleep(.5)
                    after = json.loads((project / ".carma/exploration.json").read_text(encoding="utf-8"))
                    key = next(iter(before["views"]))
                    assert before["views"][key] == after["views"][key], (before, after)
                    assert not self.window.evaluate_js("document.querySelector('.banner-error')?.textContent")
                    outcome.update(ok=True, saved=after, text=self.window.evaluate_js("document.body.innerText"))
                except Exception:
                    outcome.update(ok=False, error=traceback.format_exc(), text=self.window.evaluate_js("document.body.innerText"))
                finally:
                    (directory / "result.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
                    self.window.destroy()

            webview.start(exercise, gui="edgechromium" if sys.platform == "win32" else None)

    result = start(CheckWindow())
    print(json.dumps({"result": str(directory), "ok": outcome.get("ok")}, indent=2))
    if not outcome.get("ok"):
        print(outcome.get("error", "Window did not finish").encode("ascii", errors="backslashreplace").decode())
    return result if outcome.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
