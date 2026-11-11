"""Projects, and tasks within them. Nothing here assumes a particular project: the platform lists the
ones you can see (GET /api/v1/projects) and every task call goes to /api/v1/projects/<project>/tasks/<task>.

Which project a command works in: `--project`, else STATIONHOUSE_PROJECT, else the one you picked
with `stationhouse project use`, else the only one there is. A task id on its own is enough for task
commands: if it lives in another project, the platform says which and the call follows it.
"""
import urllib.parse

from . import config, pm
from .client import ApiError, NotFound, request
from .store import load_settings, save_settings


def list_projects() -> list[dict]:
    return (request("GET", "/api/v1/projects") or {}).get("projects", [])


def chosen(flag: str | None = None) -> str | None:
    """The project named for this command or picked earlier, without asking the platform."""
    return flag or config.project_env() or load_settings().get("project") or None


def use(project_id: str) -> dict:
    """Checks the project exists for you, then remembers it. Returns it."""
    project = request("GET", f"/api/v1/projects/{_q(project_id)}")["project"]
    settings = load_settings()
    settings["project"] = project["id"]
    save_settings(settings)
    return project


def forget() -> bool:
    settings = load_settings()
    had = settings.pop("project", None) is not None
    save_settings(settings)
    return had


def resolve(flag: str | None = None) -> str:
    """The project to work in; the only one if you can see just one; otherwise asks you to pick."""
    project = chosen(flag)
    if project:
        return project
    projects = list_projects()
    if len(projects) == 1:
        return projects[0]["id"]
    if not projects:
        raise ApiError("You can't see any projects yet.")
    names = ", ".join(p["id"] for p in projects)
    raise ApiError(f"Which project? You can see: {names}. Pick one with `stationhouse project use <id>`, or add --project <id>.")


def project_path(project_id: str, suffix: str = "") -> str:
    return f"/api/v1/projects/{_q(project_id)}{suffix}"


def task_call(method: str, task_id: str, suffix: str = "", flag: str | None = None, body: dict | None = None) -> tuple[str, object]:
    """Calls /projects/<p>/tasks/<task_id><suffix>. Without --project, a task that turns out to be in
    another project is followed there (the platform's 404 names it). Returns (project, response).

    A project-management task is named by its number: `12` (or `#12`) in the project you're in,
    `llm-self-attribution#12` in that one."""
    named, task_id = pm.split_ref(task_id)
    project = named or chosen(flag)
    if project is None and pm.is_number(task_id):
        # A number means nothing without its project: the only one you see, or the one you pick.
        project = resolve(flag)
    if project is None:
        # No project picked: any visible one works as a starting point, since the platform redirects.
        projects = list_projects()
        if not projects:
            raise ApiError("You can't see any projects yet.")
        project = projects[0]["id"]
    try:
        return project, request(method, _task_path(project, task_id, suffix), body)
    except ApiError as e:
        moved = e.body.get("projectId") if e.status == 404 else None
        if not moved or moved == project or flag or named:
            raise _not_found(e, task_id) from None
        return moved, request(method, _task_path(moved, e.body.get("taskId") or task_id, suffix), body)


def _not_found(e: ApiError, task_id: str) -> ApiError:
    """The platform's 404 for an unknown task (or one in a project the caller may not see, which it
    answers alike) as "Not found: <id>"; any other error as it was."""
    if e.status == 404 and e.body.get("error") in ("Unknown task.", "Unknown project."):
        return NotFound(f"Not found: {task_id}", 404, e.body)
    return e


def _task_path(project: str, task_id: str, suffix: str) -> str:
    return project_path(project, f"/tasks/{_q(task_id)}{suffix}")


def _q(part: str) -> str:
    return urllib.parse.quote(part, safe="")
