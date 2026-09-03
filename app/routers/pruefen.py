"""Prüfen und korrigieren - die Ansicht, für die das Ganze gebaut wird."""

from __future__ import annotations

import json
import re
from pathlib import Path

import fitz
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from config import BASE_DIR, PAGE_VIEW_WIDTH

from begutachtung.cache import CACHE_ROOT
from begutachtung.gold import Correction, add, load

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

DIGEST_RE = re.compile(r"^[0-9a-f]{12}$")
# Ab diesen Werten wird eine Zeile farblich abgesetzt.
KONF_HOCH, KONF_MITTEL = 0.85, 0.60


# ------------------------------------------------------------------ Seiten


def _page_dir(digest: str, page: int) -> Path:
    """Verzeichnis einer Seite im Zwischenspeicher, mit Prüfung.

    Digest und Seitenzahl kommen aus der URL. Beide werden gegen ein Muster
    geprüft, statt sie an den Pfad zu hängen - sonst wäre `../..` ein gültiger
    Digest und die Route ein Leseweg auf das ganze Dateisystem.
    """
    if not DIGEST_RE.match(digest or "") or not 1 <= page <= 10_000:
        raise HTTPException(status_code=404, detail="Unbekannte Seite")
    path = CACHE_ROOT / digest / "pages" / f"{page:04d}"
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Seite nicht im Zwischenspeicher")
    return path


def _lines(digest: str, page: int) -> tuple[list[dict], Path]:
    """Erkannte Zeilen einer Seite plus der Pfad ihres Bildes.

    Das Engine-Ergebnis wird per Glob gesucht statt über den Parameter-Hash
    rekonstruiert: die Ansicht muss auch dann funktionieren, wenn der Lauf mit
    anderer Auflösung oder Sprache lief.
    """
    d = _page_dir(digest, page)
    results = sorted(d.glob("eng.tesseract@*.json"), key=lambda p: p.stat().st_mtime)
    if not results:
        raise HTTPException(status_code=404, detail="Für diese Seite gibt es kein Ergebnis")
    data = json.loads(results[-1].read_text(encoding="utf-8"))
    images = sorted(d.glob("raw.dpi*.png"))
    if not images:
        raise HTTPException(status_code=404, detail="Seitenbild fehlt")
    return data.get("lines", []), images[-1]


def _konf_klasse(conf: float | None) -> str:
    if conf is None:
        return "zeile-mittel"
    if conf >= KONF_HOCH:
        return "zeile-hoch"
    if conf >= KONF_MITTEL:
        return "zeile-mittel"
    return "zeile-niedrig"


@router.get("/bild/{digest}/{page}")
def bild(digest: str, page: int, w: int = PAGE_VIEW_WIDTH):
    """Ein Seitenbild ausliefern, auf Anzeigebreite verkleinert.

    Die zwischengespeicherten Bilder sind bei 400 dpi rund 3300 x 4700 Pixel.
    Ungefiltert wären das mehrere Megabyte je Seite; die verkleinerte Fassung
    wird einmal erzeugt und daneben abgelegt.
    """
    d = _page_dir(digest, page)
    images = sorted(d.glob("raw.dpi*.png"))
    if not images:
        raise HTTPException(status_code=404, detail="Seitenbild fehlt")
    original = images[-1]

    w = max(200, min(w, 4000))
    if w >= 3000:
        return FileResponse(original, media_type="image/png")

    scaled = d / f"view.w{w}.png"
    if not scaled.exists():
        with fitz.open(original) as doc:
            src = doc[0]
            zoom = w / src.rect.width
            src.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).save(scaled)
    return FileResponse(scaled, media_type="image/png")


# ----------------------------------------------------------------- Ansicht


@router.get("/pruefen", response_class=HTMLResponse)
def pruefen_page(request: Request, pdf: str, seite: int = 0):
    pdf_path = Path(pdf)
    if not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="PDF nicht gefunden")

    from begutachtung.cache import DocumentCache
    cache = DocumentCache(pdf_path)
    digest = cache.digest

    report_pages = _report_pages(digest, pdf_path)
    if not report_pages:
        raise HTTPException(status_code=404,
                            detail="Diese Datei wurde noch nicht analysiert")

    # Schlechteste zuerst - wer prüft, will dort anfangen, wo es weh tut.
    reihenfolge = [p["page"] for p in sorted(
        report_pages, key=lambda p: (p.get("mean_conf") is None, p.get("mean_conf") or 0))]
    aktuell = seite or reihenfolge[0]

    lines, image = _lines(digest, aktuell)
    korrekturen = load(digest)
    with fitz.open(image) as doc:
        breite = doc[0].rect.width
    skala = PAGE_VIEW_WIDTH / breite

    info = next((p for p in report_pages if p["page"] == aktuell), {})
    return templates.TemplateResponse(request, "pruefen.html", {
        "request": request,
        "pdf": pdf_path,
        "digest": digest,
        "seite": aktuell,
        "reihenfolge": reihenfolge,
        "position": reihenfolge.index(aktuell) + 1 if aktuell in reihenfolge else 0,
        "zeilen": _zeilen_kontext(lines, korrekturen, aktuell, skala),
        "info": info,
        "skala": skala,
        "bildbreite": PAGE_VIEW_WIDTH,
        "korrigiert_gesamt": len(korrekturen),
        "seiten_gesamt": len(report_pages),
        "unsicher_gesamt": sum(1 for p in report_pages if p.get("escalate")),
    })


@router.post("/pruefen/korrektur", response_class=HTMLResponse)
def korrektur(
    request: Request,
    digest: str = Form(...),
    seite: int = Form(...),
    index: int = Form(...),
    text: str = Form(...),
    ocr: str = Form(...),
    conf: str = Form(""),
):
    """Eine korrigierte Zeile speichern und als Fragment zurückgeben."""
    lines, image = _lines(digest, seite)
    if not 0 <= index < len(lines):
        raise HTTPException(status_code=404, detail="Zeile nicht gefunden")

    line = lines[index]
    bbox = line.get("bbox") or {}
    add(digest, Correction(
        page=seite, line=index, ocr=ocr, gold=text.strip(),
        bbox=[bbox.get("left", 0), bbox.get("top", 0),
              bbox.get("width", 0), bbox.get("height", 0)] if bbox else None,
        conf=float(conf) if conf else None,
    ))

    with fitz.open(image) as doc:
        skala = PAGE_VIEW_WIDTH / doc[0].rect.width
    kontext = _zeilen_kontext(lines, load(digest), seite, skala)
    return templates.TemplateResponse(request, "partials/zeile.html", {
        "request": request, "z": kontext[index], "digest": digest, "seite": seite,
    })


# ------------------------------------------------------------------ intern


def _report_pages(digest: str, pdf_path: Path) -> list[dict]:
    """Die Seitenbewertung des jüngsten Laufs über diese Datei."""
    from config import RUNS_DIR
    from begutachtung.runstate import list_runs

    for run in list_runs(root=RUNS_DIR):
        state = run.read_state()
        if not state or Path(state.source) != pdf_path:
            continue
        report = run.path / "report.json"
        if report.exists():
            try:
                return json.loads(report.read_text(encoding="utf-8")).get("pages", [])
            except json.JSONDecodeError:
                continue

    # Kein Lauf-Bericht - aus dem Zwischenspeicher rekonstruieren, damit die
    # Ansicht auch nach einem `analyze` von Hand funktioniert.
    pages_dir = CACHE_ROOT / digest / "pages"
    if not pages_dir.is_dir():
        return []
    return [{"page": int(d.name), "mean_conf": None, "escalate": False}
            for d in sorted(pages_dir.iterdir())
            if d.is_dir() and any(d.glob("eng.tesseract@*.json"))]


def _zeilen_kontext(lines: list[dict], korrekturen: dict, seite: int,
                    skala: float) -> list[dict]:
    out = []
    for i, line in enumerate(lines):
        bbox = line.get("bbox") or {}
        korrektur = korrekturen.get((seite, i))
        out.append({
            "index": i,
            "text": korrektur.gold if korrektur else line.get("text", ""),
            "ocr": line.get("text", ""),
            "conf": line.get("conf"),
            "klasse": "zeile-korrigiert" if korrektur else _konf_klasse(line.get("conf")),
            "korrigiert": korrektur is not None,
            "bbox": bbox,
            # Der Ausschnitt wird per negativem Rand aus dem vollen Seitenbild
            # geschnitten - das spart tausende Zuschnittdateien.
            "crop_w": int(bbox.get("width", 0) * skala),
            "crop_h": int(bbox.get("height", 0) * skala),
            "crop_x": int(bbox.get("left", 0) * skala),
            "crop_y": int(bbox.get("top", 0) * skala),
        })
    return out
