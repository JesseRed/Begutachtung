"""Fallordner erkennen und ihren Zustand ermitteln.

Ein Fall ist ein Ordner mit `Akte.pdf`, `Anschreiben.pdf` und Verwandtem - so
liegt der reale Korpus. Die Arbeitseinheit ist deshalb der Ordner, nicht die
einzelne Datei.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from config import RECENT_FILE, STATE_DIR

from begutachtung.cache import DocumentCache
from begutachtung.pdfio import inspect

MAX_RECENT = 12


@dataclass
class DateiStatus:
    path: Path
    pages: int
    has_text_layer: bool
    digest: str
    analysiert: int
    """Wie viele Seiten bereits im Zwischenspeicher liegen."""
    unsicher: int | None
    ocr_pdf: Path | None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def fortschritt(self) -> int:
        return int(100 * self.analysiert / self.pages) if self.pages else 0

    @property
    def vollstaendig(self) -> bool:
        return self.pages > 0 and self.analysiert >= self.pages


def ist_ocr_ergebnis(path: Path) -> bool:
    """Eigene Ergebnisse sind keine Eingaben - sonst analysiert man sie erneut."""
    return path.name.startswith("OCR_") or path.stem.endswith("_OCR")


def pdfs_im_ordner(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("*.pdf") if not ist_ocr_ergebnis(p))


def status_fuer(pdf: Path) -> DateiStatus:
    info = inspect(pdf)
    cache = DocumentCache(pdf)

    # Wie weit ist die Analyse? Zaehlen, fuer wie viele Seiten ein
    # Engine-Ergebnis im Zwischenspeicher liegt.
    analysiert = 0
    unsicher: int | None = None
    pages_dir = cache.root / "pages"
    if pages_dir.exists():
        analysiert = sum(1 for d in pages_dir.iterdir()
                         if d.is_dir() and any(d.glob("eng.tesseract@*.json")))

    ocr_pdf = pdf.with_name(f"OCR_{pdf.name}")
    return DateiStatus(
        path=pdf,
        pages=info.page_count,
        has_text_layer=info.has_text_layer,
        digest=cache.digest,
        analysiert=analysiert,
        unsicher=unsicher,
        ocr_pdf=ocr_pdf if ocr_pdf.exists() else None,
    )


# ------------------------------------------------------- zuletzt geöffnet


def recent() -> list[str]:
    try:
        data = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
        return [p for p in data if Path(p).is_dir()]
    except (OSError, json.JSONDecodeError, TypeError):
        return []


def remember(folder: Path) -> None:
    entries = [str(folder)] + [p for p in recent() if p != str(folder)]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = RECENT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries[:MAX_RECENT], ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(RECENT_FILE)
