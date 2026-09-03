"""Der Durchlauf über ein Dokument: rastern, lesen, bewerten.

Das ist die Stufe 1 der Kaskade. Sie läuft auf allen Seiten, kostet nichts außer
CPU-Zeit, und ihr Ergebnis entscheidet, welche Seiten überhaupt für ein
Bildsprachmodell in Frage kommen.

Alles Teure wird gecacht: ein zweiter Lauf mit anderen Schwellen rechnet die
Bewertung neu, aber nicht die OCR.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Iterable

from .cache import DocumentCache
from .classify import classify_page, image_stats
from .confidence import PageClass, Thresholds, assess, load_lexicon
from .engines.base import Line, PageResult, Word
from .engines.tesseract import TesseractEngine
from .pdfio import inspect, rasterize_page

ProgressFn = Callable[[int, int, int], None]


def analyze_document(
    pdf_path: str | Path,
    dpi: int = 400,
    langs: str = "deu+eng",
    pages: Iterable[int] | None = None,
    tessdata_dir: Path | None = None,
    lexicon_path: Path | None = None,
    thresholds: Thresholds | None = None,
    on_progress: ProgressFn | None = None,
) -> dict:
    pdf_path = Path(pdf_path)
    info = inspect(pdf_path)
    cache = DocumentCache(pdf_path)
    cache.write_meta(info.page_count, {"dpi": dpi, "langs": langs})

    engine = TesseractEngine(langs=langs, tessdata_dir=tessdata_dir)
    lexicon = load_lexicon(str(lexicon_path) if lexicon_path else None)
    th = thresholds or Thresholds()

    wanted = [p for p in (pages or range(1, info.page_count + 1))
              if 1 <= p <= info.page_count]

    params = {"dpi": dpi, "langs": langs, "psm": engine.psm,
              "tessdata": "best" if tessdata_dir else "image"}
    started = time.monotonic()
    rows: list[dict] = []

    for n, page_no in enumerate(wanted, start=1):
        if on_progress:
            on_progress(n, len(wanted), page_no)

        image = cache.image_path(page_no, "raw", dpi)
        if not image.exists():
            rasterize_page(pdf_path, page_no - 1, image, dpi=dpi)

        result_file = cache.result_path(page_no, engine.info.name, "5.5.1", params)
        cached = cache.load_json(result_file)
        if cached:
            result = _result_from_dict(cached)
        else:
            result = engine.run(image, page=page_no)
            cache.save_json(result_file, result.to_dict())

        stats = image_stats(image)
        page_class = classify_page(stats, result)
        a = assess(result, page_class, th, lexicon, ink_coverage=stats.ink_coverage)

        rows.append({
            **asdict(a),
            "page_class": a.page_class.value,
            "reasons": a.reason_text,
            "ink_coverage": round(stats.ink_coverage, 4),
            "seconds": round(result.seconds, 2),
            "cached": bool(cached),
        })

    by_class: dict[str, int] = {}
    for row in rows:
        by_class[row["page_class"]] = by_class.get(row["page_class"], 0) + 1

    return {
        "source": str(pdf_path),
        "page_count": info.page_count,
        "dpi": dpi,
        "pages": rows,
        "summary": {
            "total": len(rows),
            "escalate": sum(1 for r in rows if r["escalate"]),
            "by_class": by_class,
            "seconds": time.monotonic() - started,
            "cache": str(cache.root),
        },
    }


def _result_from_dict(data: dict) -> PageResult:
    """Ein gecachtes Ergebnis zurueckbauen.

    Die Boxen werden hier absichtlich nicht rekonstruiert - fuer die Bewertung
    braucht es nur Text und Konfidenzen. Wer Geometrie braucht (Textlayer,
    Review-Report), laedt das JSON direkt.
    """
    lines = []
    for line in data.get("lines", []):
        words = [Word(text=w["text"], conf=w.get("conf")) for w in line.get("words", [])]
        lines.append(Line(text=line["text"], conf=line.get("conf"), words=words))
    return PageResult(
        engine=data.get("engine", "tesseract"),
        page=data.get("page", 0),
        lines=lines,
        seconds=data.get("seconds", 0.0),
        meta=data.get("meta", {}),
    )
