"""Seitenklassifikation - bewusst einfach gehalten.

Diese erste Fassung kommt ohne OpenCV aus und benutzt nur, was PyMuPDF liefert:
ein Graustufen-Histogramm der Seite plus das Tesseract-Ergebnis. Damit lassen
sich `leer`, `bild` und `druck` zuverlaessig trennen.

`formular`, `handschrift` und `tabelle` brauchen Strukturanalyse
(Linienerkennung, Strichbreiten-Varianz) und kommen mit OpenCV in einer
spaeteren Phase. Bis dahin liefert `classify_page` fuer diese Faelle
`degradiert` - was praktisch bedeutet: sie eskalieren ueber die Konfidenz- und
Lexikonschwelle statt ueber die Klasse. Das ist schlechter als eine echte
Klassifikation, aber nicht falsch.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz

from .confidence import PageClass
from .engines.base import PageResult

# Graustufen unter diesem Wert gelten als Tinte.
INK_THRESHOLD = 160
# Jeder n-te Pixel wird betrachtet. Bei 400 dpi sind das immer noch >100k
# Stichproben pro Seite - fuer einen Flaechenanteil weit mehr als genug.
SUBSAMPLE = 37


@dataclass
class PageStats:
    ink_coverage: float
    """Anteil dunkler Pixel."""
    midtone_ratio: float
    """Anteil mittlerer Grauwerte - hoch bei Fotos und Roentgenbildern,
    niedrig bei Text, der fast nur aus Schwarz und Weiss besteht."""


def image_stats(image_path: str | Path) -> PageStats:
    pix = fitz.Pixmap(str(image_path))
    if pix.n > 1:  # in Graustufen wandeln, falls farbig gerastert wurde
        pix = fitz.Pixmap(fitz.csGRAY, pix)
    data = pix.samples
    total = ink = mid = 0
    for i in range(0, len(data), SUBSAMPLE):
        value = data[i]
        total += 1
        if value < INK_THRESHOLD:
            ink += 1
        if 70 <= value <= 200:
            mid += 1
    if not total:
        return PageStats(0.0, 0.0)
    return PageStats(ink / total, mid / total)


def classify_page(stats: PageStats, result: PageResult | None = None) -> PageClass:
    """Seitenklasse aus Bildstatistik und OCR-Ergebnis.

    Reihenfolge ist wichtig: erst die Faelle, in denen OCR sinnlos ist.
    """
    words = result.word_count if result else 0
    conf = result.mean_conf if result else None

    # Fast nichts auf der Seite.
    if stats.ink_coverage < 0.003 and words < 5:
        return PageClass.LEER

    # Viel mittleres Grau und kaum Text: Roentgenbild, Foto, gescanntes Diagramm.
    # OCR darauf kostet Zeit und liefert Rauschen.
    if stats.midtone_ratio > 0.35 and words < 25:
        return PageClass.BILD

    if conf is not None and conf >= 0.85:
        return PageClass.DRUCK

    # Alles Uebrige ist irgendeine Form von schlecht lesbar. Die feinere
    # Unterscheidung (Formular, Handschrift, Tabelle) folgt mit OpenCV.
    return PageClass.DEGRADIERT
