"""Gemeinsame Datenstrukturen aller OCR-Engines.

Jede Engine liefert dasselbe `PageResult`, damit die Routing-Matrix Tesseract,
ein lokales VLM und Claude beliebig kombinieren kann. Die Geometrie kommt in der
Praxis von Tesseract - Bildsprachmodelle liefern guten Text, aber unzuverlaessige
Koordinaten. Deshalb darf `bbox` None sein.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class BBox:
    """Rechteck in Pixeln des vorverarbeiteten Seitenbilds."""

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def area(self) -> int:
        return self.width * self.height

    def iou(self, other: BBox) -> float:
        """Ueberlappung zweier Boxen - fuer das Zuordnen von Zeilen zwischen Engines."""
        ix = max(0, min(self.right, other.right) - max(self.left, other.left))
        iy = max(0, min(self.bottom, other.bottom) - max(self.top, other.top))
        inter = ix * iy
        union = self.area + other.area - inter
        return inter / union if union else 0.0


@dataclass
class Word:
    text: str
    bbox: BBox | None = None
    conf: float | None = None
    """0.0-1.0. Tesseract liefert 0-100, das wird beim Einlesen normalisiert."""


@dataclass
class Line:
    text: str
    bbox: BBox | None = None
    conf: float | None = None
    words: list[Word] = field(default_factory=list)

    @property
    def mean_word_conf(self) -> float | None:
        confs = [w.conf for w in self.words if w.conf is not None]
        return sum(confs) / len(confs) if confs else None


@dataclass
class PageResult:
    """Was eine Engine zu einer Seite zu sagen hat."""

    engine: str
    page: int
    lines: list[Line] = field(default_factory=list)
    seconds: float = 0.0
    cost_usd: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def word_count(self) -> int:
        return sum(len(line.words) or len(line.text.split()) for line in self.lines)

    @property
    def mean_conf(self) -> float | None:
        """Laengengewichtet - eine lange sichere Zeile wiegt schwerer als ein
        einzelnes unsicheres Wort am Seitenrand."""
        pairs = [(line.conf, len(line.text)) for line in self.lines if line.conf is not None]
        total = sum(n for _, n in pairs)
        if not total:
            return None
        return sum(c * n for c, n in pairs) / total

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EngineInfo:
    """Was eine Engine ist - nicht nur wie sie heisst.

    Zwei Felder tragen hier die Last des ganzen Sicherheitsentwurfs:

    `is_local` ist die *einzige* Stelle, an der die Unterscheidung lokal/Cloud
    kodiert ist. Das Freigabe-Gate sammelt die Seiten, die an eine Engine mit
    `is_local=False` gehen wuerden; das Audit-Log protokolliert genau diese
    Aufrufe; der Schalter "Daten duerfen ins Internet" filtert danach. Nirgends
    im Code steht `if engine == "claude"` - sonst waere die naechste Engine eine
    Luecke.

    `provides_geometry` haelt fest, dass nur Tesseract verlaessliche Wortboxen
    liefert. Die Zusammenfuehrung besteht darauf, dass genau eine solche Engine
    je Seite gelaufen ist, und benutzt sie als Skelett. Damit ist es strukturell
    unmoeglich, dass erfundene Koordinaten eines Bildmodells in den Textlayer
    geraten.
    """

    name: str
    is_local: bool
    provides_geometry: bool
    model_id: str
    version: str
    """Geht in den Cache-Schluessel - ein Modellwechsel invalidiert Ergebnisse."""


@dataclass(frozen=True)
class Estimate:
    """Was ein Lauf voraussichtlich kostet.

    Die Spanne ist nicht Zierde: die Eingabetokens eines Bildes stehen vorher
    fest, die Ausgabelaenge nicht. Ein Kostendeckel muss gegen die OBERE Schranke
    pruefen, sonst leckt er um ein Mehrfaches.
    """

    seconds: float
    usd_low: float = 0.0
    usd_high: float = 0.0
    calibrated_from_runs: int = 0
    """0 heisst: geraten. Das gehoert in der Oberflaeche dazugesagt."""


class Engine(Protocol):
    """Was eine Engine koennen muss."""

    info: EngineInfo

    def available(self) -> tuple[bool, str]: ...

    def run(self, image_path: str, page: int) -> PageResult: ...

    def estimate(self, n_pages: int) -> Estimate: ...
