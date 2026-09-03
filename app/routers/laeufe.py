from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import BASE_DIR, RUNS_DIR

from begutachtung.runstate import CANCELLED, DONE, FAILED, RUNNING, find_run, list_runs

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

STATUS_TEXT = {
    RUNNING: "läuft",
    DONE: "fertig",
    CANCELLED: "abgebrochen",
    FAILED: "fehlgeschlagen",
}


def _kontext(run, request: Request) -> dict:
    state = run.read_state()
    status = run.effective_status()
    config = run.read_config()
    quelle = Path(state.source) if state else None
    return {
        "request": request,
        "run": run,
        "state": state,
        "status": status,
        "status_text": STATUS_TEXT.get(status, status),
        "config": config,
        "quelle": quelle,
        "ereignisse": run.tail_events(25),
    }


@router.get("/laeufe", response_class=HTMLResponse)
def laeufe_page(request: Request):
    eintraege = []
    for run in list_runs(root=RUNS_DIR):
        state = run.read_state()
        if state is None:
            continue
        status = run.effective_status()
        eintraege.append({
            "id": run.id, "state": state, "status": status,
            "status_text": STATUS_TEXT.get(status, status),
            "name": Path(state.source).name,
        })
    return templates.TemplateResponse(request, "laeufe.html",
                                      {"request": request, "eintraege": eintraege})


@router.get("/laeufe/{run_id}", response_class=HTMLResponse)
def lauf_page(request: Request, run_id: str):
    run = find_run(run_id, root=RUNS_DIR)
    if run is None:
        raise HTTPException(status_code=404, detail="Lauf nicht gefunden")
    return templates.TemplateResponse(request, "lauf.html", _kontext(run, request))


@router.get("/laeufe/{run_id}/status", response_class=HTMLResponse)
def lauf_status(request: Request, run_id: str):
    """Das Fragment, das HTMX alle zwei Sekunden holt.

    Es rendert sich selbst samt `hx-trigger` - ist der Lauf fertig, lässt das
    Fragment das Attribut weg und das Polling hört von selbst auf. Kein
    JavaScript, kein Aufräumen.
    """
    run = find_run(run_id, root=RUNS_DIR)
    if run is None:
        raise HTTPException(status_code=404, detail="Lauf nicht gefunden")
    return templates.TemplateResponse(request, "partials/lauf_status.html", _kontext(run, request))


@router.post("/laeufe/{run_id}/abbrechen")
def lauf_abbrechen(run_id: str):
    run = find_run(run_id, root=RUNS_DIR)
    if run is None:
        raise HTTPException(status_code=404, detail="Lauf nicht gefunden")
    run.request_cancel()
    return RedirectResponse(url=f"/laeufe/{run_id}", status_code=303)
