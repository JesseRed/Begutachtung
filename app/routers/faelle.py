from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services import runner
from app.services.faelle import pdfs_im_ordner, recent, remember, status_fuer
from config import BASE_DIR, DEFAULT_CASE_ROOT

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@router.get("/", response_class=HTMLResponse)
def faelle_page(request: Request):
    vorschlaege = []
    if DEFAULT_CASE_ROOT.is_dir():
        vorschlaege = sorted(d for d in DEFAULT_CASE_ROOT.iterdir() if d.is_dir())
    return templates.TemplateResponse(request, "faelle.html",
        {
            "request": request,
            "vorschlaege": vorschlaege,
            "zuletzt": recent(),
            "sammelordner": DEFAULT_CASE_ROOT,
        },
    )


@router.post("/oeffnen", response_class=HTMLResponse)
def oeffnen(request: Request, pfad: str = Form(...)):
    """Einen Ordner per Pfad öffnen.

    Wie in TangoTrainers Einstellungen: ein Textfeld statt eines Auswahldialogs
    (den es im Browser für Ordner nicht gibt), serverseitig geprüft.
    """
    pfad = pfad.strip()
    folder = Path(pfad).expanduser()
    if not folder.is_dir():
        vorschlaege = sorted(d for d in DEFAULT_CASE_ROOT.iterdir()
                             if d.is_dir()) if DEFAULT_CASE_ROOT.is_dir() else []
        return templates.TemplateResponse(request, "faelle.html",
            {
                "request": request,
                "vorschlaege": vorschlaege,
                "zuletzt": recent(),
                "sammelordner": DEFAULT_CASE_ROOT,
                "error": f"Kein Verzeichnis: {pfad}",
                "form_pfad": pfad,
            },
            status_code=422,
        )
    remember(folder)
    return RedirectResponse(url=f"/fall?pfad={folder}", status_code=303)


@router.get("/fall", response_class=HTMLResponse)
def fall_page(request: Request, pfad: str):
    folder = Path(pfad)
    if not folder.is_dir():
        return RedirectResponse(url="/", status_code=303)

    dateien = [status_fuer(p) for p in pdfs_im_ordner(folder)]
    return templates.TemplateResponse(request, "fall.html",
        {"request": request, "ordner": folder, "dateien": dateien},
    )


@router.post("/fall/analysieren")
def analysieren(
    pfad: str = Form(...),
    pdf: str = Form(...),
    dpi: int = Form(400),
    seiten: str = Form(""),
    lexikon: str = Form(""),
):
    run = runner.start_analyze(Path(pdf), dpi=dpi, pages=seiten.strip(),
                               lexicon=bool(lexikon))
    return RedirectResponse(url=f"/laeufe/{run.id}", status_code=303)


@router.post("/fall/ocr")
def ocr_erzeugen(pfad: str = Form(...)):
    run = runner.start_ocr(Path(pfad))
    return RedirectResponse(url=f"/laeufe/{run.id}", status_code=303)
