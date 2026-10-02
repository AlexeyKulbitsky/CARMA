"""Project operations exposed to every renderer through the View API."""

from fastapi import APIRouter, Request
from starlette.exceptions import HTTPException

from carma.api import schemas as s
from carma.application.manager import ProjectManager
from carma.application.preparation import ApplicationError


def manager(request: Request) -> ProjectManager:
    service = request.app.state.manager
    if service is None:
        raise HTTPException(409, "Project management is available in the CARMA application.")
    return service


def build_application_router(prefix: str) -> APIRouter:
    r = APIRouter(prefix=prefix, responses={400: {"model": s.ErrorResponse}, 409: {"model": s.ErrorResponse},
                                          422: {"model": s.ErrorResponse}})

    @r.get("/app/state", response_model=s.ApplicationState)
    def state(request: Request):
        service = request.app.state.manager
        return service.state() if service else s.ApplicationState(managed=False)

    @r.post("/app/pick-folder", response_model=s.FolderChoice)
    def pick_folder(request: Request):
        manager(request)
        picker = request.app.state.choose_folder
        if picker is None:
            raise ApplicationError("Folder selection is unavailable in this client.")
        return {"path": picker()}

    @r.post("/app/inspect", response_model=s.ProjectInspection)
    def inspect(request: Request, body: s.ProjectPath):
        return manager(request).inspect(body.path)

    @r.post("/app/open", response_model=s.ApplicationState)
    def open_project(request: Request, body: s.OpenProject):
        return manager(request).open(body.path, body.build_id, replace_id=body.replace_id)

    @r.post("/app/reindex", response_model=s.ApplicationState)
    def reindex(request: Request):
        service = manager(request)
        state = service.state()
        if not state["active"]:
            raise ApplicationError("Open a project first.", "no_project")
        return service.open(state["active"]["path"], reindex=True)

    @r.post("/app/cancel", response_model=s.ApplicationState)
    def cancel(request: Request):
        return manager(request).cancel()

    @r.post("/app/close", response_model=s.ApplicationState)
    def close(request: Request):
        return manager(request).close_project()

    @r.post("/app/forget", response_model=s.ApplicationState)
    def forget(request: Request, body: s.RecentProject):
        return manager(request).forget(body.id)

    return r
