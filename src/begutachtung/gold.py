"""Korrigierte Zeilen - der Referenzsatz, der beim Prüfen nebenbei entsteht.

Der ursprüngliche Plan sah vor, für die Messung einen Nachmittag lang Zeilen
abzutippen. Das ist unnötig: beim Durchsehen einer Akte wird eine falsch
erkannte Zeile ohnehin gelesen und gedanklich korrigiert. Wird diese Korrektur
mitgeschrieben, entsteht der Referenzsatz als Nebenprodukt der Arbeit, die
sowieso anfällt.

Format ist JSONL, angehängt statt überschrieben - so geht bei einem Absturz
höchstens die letzte Zeile verloren. Mehrfach korrigierte Zeilen stehen mehrfach
in der Datei; beim Lesen gewinnt die jüngste. Das erhält nebenbei die Historie.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

GOLD_ROOT = Path(__file__).resolve().parents[2] / "eval" / "gold"


@dataclass
class Correction:
    page: int
    line: int
    ocr: str
    gold: str
    bbox: list[int] | None = None
    conf: float | None = None
    engine: str = "tesseract"
    ts: float = 0.0

    @property
    def unchanged(self) -> bool:
        """Eine bestätigte Zeile ist auch ein Datenpunkt - sie belegt, dass die
        Erkennung hier richtig lag."""
        return self.ocr.strip() == self.gold.strip()


def _file(digest: str, root: Path = GOLD_ROOT) -> Path:
    return Path(root) / digest / "lines.jsonl"


def add(digest: str, correction: Correction, root: Path = GOLD_ROOT) -> Correction:
    correction.ts = correction.ts or time.time()
    path = _file(digest, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(correction), ensure_ascii=False) + "\n")
    return correction


def load(digest: str, root: Path = GOLD_ROOT) -> dict[tuple[int, int], Correction]:
    """Alle Korrekturen eines Dokuments, je Zeile die jüngste."""
    path = _file(digest, root)
    out: dict[tuple[int, int], Correction] = {}
    if not path.exists():
        return out
    known = set(Correction.__dataclass_fields__)
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue  # abgeschnittene letzte Zeile nach einem Absturz
        try:
            c = Correction(**{k: v for k, v in data.items() if k in known})
        except TypeError:
            continue
        out[(c.page, c.line)] = c
    return out


def count(digest: str, root: Path = GOLD_ROOT) -> int:
    return len(load(digest, root))
