"""PDF ein- und ausgeben: rastern, Seitenzahlen zaehlen, Textlayer pruefen.

Die harte Invariante des ganzen Projekts steht hier: die Seitenzahl der Ausgabe
muss der Eingabe entsprechen, sonst brechen die Seitenbereiche in
extract_list.csv. Deshalb wird der Textlayer spaeter ueber die unveraenderten
Originalseiten gelegt und nicht wie bei --force-ocr neu gerastert.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF


@dataclass(frozen=True)
class PdfInfo:
    path: Path
    page_count: int
    text_chars: int
    """Zeichen im vorhandenen Textlayer der ersten Seiten - 0 heisst reiner Scan."""

    @property
    def has_text_layer(self) -> bool:
        return self.text_chars > TEXT_LAYER_MIN_CHARS


TEXT_LAYER_MIN_CHARS = 500
PROBE_PAGES = 3


def inspect(pdf_path: str | Path) -> PdfInfo:
    path = Path(pdf_path)
    with fitz.open(path) as doc:
        chars = sum(
            len((doc[i].get_text() or "").strip())
            for i in range(min(PROBE_PAGES, doc.page_count))
        )
        return PdfInfo(path=path, page_count=doc.page_count, text_chars=chars)


def rasterize_page(
    pdf_path: str | Path,
    page_index: int,
    out_path: str | Path,
    dpi: int = 400,
    grayscale: bool = True,
) -> Path:
    """Eine Seite als PNG ablegen.

    get_pixmap beachtet den /Rotate-Eintrag der Seite, bereits gedrehte Seiten
    werden also aufrecht gerendert. Die Rotation wird trotzdem mitgeschrieben,
    weil Boxen spaeter auf die Originalseite zurueckgerechnet werden muessen.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf_path) as doc:
        page = doc[page_index]
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY if grayscale else fitz.csRGB)
        pix.save(out)
    return out


def page_rotation(pdf_path: str | Path, page_index: int) -> int:
    with fitz.open(pdf_path) as doc:
        return doc[page_index].rotation


def assert_page_count(source: str | Path, produced: str | Path) -> None:
    """Die Invariante, von der extractor.py abhaengt.

    Absichtlich eine harte Pruefung und keine Warnung: eine verschobene
    Seitenzahl faellt sonst erst auf, wenn ein Gutachten den falschen Befund
    zitiert.
    """
    a, b = inspect(source).page_count, inspect(produced).page_count
    if a != b:
        raise ValueError(
            f"Seitenzahl veraendert: {Path(source).name} hat {a}, "
            f"{Path(produced).name} hat {b}. Das bricht die Seitenbereiche in "
            f"extract_list.csv."
        )
