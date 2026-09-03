"""Kommandozeile.

Bewusst duenn: die Kommandos bauen eine Konfiguration und rufen die Pipeline.
Dieselbe Pipeline wird spaeter vom Dashboard aufgerufen, damit beide Wege
identisch rechnen und die CLI skriptbar bleibt.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from . import __version__
from .analyze import analyze_document
from .cache import DocumentCache
from .pdfio import inspect

app = typer.Typer(
    add_completion=False,
    help="OCR-Pipeline für gescannte medizinische Begutachtungs-Akten.",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TESSDATA = REPO_ROOT / "docker" / "tessdata"


@app.command("inspect")
def cmd_inspect(pdf: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """Seitenzahl und Textlayer eines PDF anzeigen."""
    info = inspect(pdf)
    typer.echo(f"{info.path.name}")
    typer.echo(f"  Seiten:     {info.page_count}")
    typer.echo(f"  Textlayer:  {'ja' if info.has_text_layer else 'nein'} "
               f"({info.text_chars} Zeichen auf den ersten Seiten)")
    typer.echo(f"  Modus:      {'--redo-ocr' if info.has_text_layer else '--force-ocr + Deskew'}")


@app.command("analyze")
def cmd_analyze(
    pdf: Path = typer.Argument(..., exists=True, dir_okay=False),
    dpi: int = typer.Option(400, help="Rasterauflösung."),
    pages: str = typer.Option("", help="Seitenbereich, z.B. 1-20. Leer = alle."),
    langs: str = typer.Option("deu+eng"),
    lexicon: Path = typer.Option(None, help="Wörterliste für den Lexikon-Indikator."),
    json_out: Path = typer.Option(None, "--json", help="Ergebnis als JSON ablegen."),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Seiten rastern, mit Tesseract lesen und bewerten.

    Zeigt, welche Seiten unsicher sind - die Grundlage für jede spätere
    Eskalation an ein Bildsprachmodell.
    """
    page_range = _parse_range(pages) if pages else None

    def progress(done: int, total: int, page_no: int) -> None:
        if not quiet:
            typer.echo(f"\r  Seite {page_no}  ({done}/{total})", nl=False, err=True)

    report = analyze_document(
        pdf, dpi=dpi, langs=langs, pages=page_range,
        tessdata_dir=DEFAULT_TESSDATA if DEFAULT_TESSDATA.exists() else None,
        lexicon_path=lexicon, on_progress=None if quiet else progress,
    )
    if not quiet:
        typer.echo("\r" + " " * 40 + "\r", nl=False, err=True)

    _print_report(report)

    if json_out:
        json_out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        typer.echo(f"\nJSON: {json_out}")


@app.command("purge")
def cmd_purge(pdf: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """Zwischengespeicherte Seitenbilder und Ergebnisse löschen.

    Der Cache enthält Seitenbilder aus Patientenakten.
    """
    cache = DocumentCache(pdf)
    size = cache.size_bytes()
    cache.purge()
    typer.echo(f"Gelöscht: {size / 1e6:.1f} MB aus {cache.root}")


@app.command("version")
def cmd_version() -> None:
    typer.echo(__version__)


# ----------------------------------------------------------------- Hilfsteil


def _parse_range(spec: str) -> range:
    try:
        if "-" in spec:
            start, end = spec.split("-", 1)
            return range(int(start), int(end) + 1)
        n = int(spec)
        return range(n, n + 1)
    except ValueError:
        typer.echo(f"Seitenbereich nicht lesbar: {spec!r} (erwartet z.B. 1-20)", err=True)
        raise typer.Exit(1)


def _print_report(report: dict) -> None:
    pages = report["pages"]
    typer.echo(f"\n{report['source']}  —  {len(pages)} Seiten analysiert\n")
    typer.echo(f"  {'Seite':>5}  {'Klasse':<12} {'Wörter':>7} {'Konf':>6} {'Lex':>6}  Bewertung")
    typer.echo("  " + "─" * 76)
    for p in pages:
        conf = f"{p['mean_conf']:.2f}" if p["mean_conf"] is not None else "  —"
        lex = f"{p['lexicon_rate']:.0%}" if p["lexicon_rate"] is not None else "  —"
        mark = "!" if p["escalate"] else " "
        typer.echo(f"  {p['page']:>5}{mark} {p['page_class']:<12} {p['word_count']:>7} "
                   f"{conf:>6} {lex:>6}  {p['reasons']}")

    s = report["summary"]
    typer.echo("  " + "─" * 76)
    typer.echo(f"\n  {s['escalate']} von {s['total']} Seiten brauchen eine zweite Meinung "
               f"({s['escalate'] / max(s['total'], 1):.0%})")
    if s["by_class"]:
        typer.echo("  Klassen: " + ", ".join(f"{k} {v}" for k, v in sorted(s["by_class"].items())))
    typer.echo(f"  Laufzeit: {s['seconds']:.1f} s "
               f"({s['seconds'] / max(s['total'], 1):.1f} s/Seite)")


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        typer.echo("\nAbgebrochen.", err=True)
        sys.exit(130)


if __name__ == "__main__":
    main()
