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
from .analyze import Cancelled, analyze_document
from .cache import DocumentCache
from .pdfio import inspect
from .runstate import CANCELLED, DONE, FAILED, RUNNING, RunDir, find_run, list_runs

app = typer.Typer(
    add_completion=False,
    help="OCR-Pipeline für gescannte medizinische Begutachtungs-Akten.",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TESSDATA = REPO_ROOT / "docker" / "tessdata"

_STATUS_TEXT = {
    RUNNING: "läuft",
    DONE: "fertig",
    CANCELLED: "abgebrochen",
    FAILED: "fehlgeschlagen",
}


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
    run_dir: Path = typer.Option(None, "--run-dir",
                                 help="Fortschritt in dieses Lauf-Verzeichnis schreiben."),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Seiten rastern, mit Tesseract lesen und bewerten.

    Zeigt, welche Seiten unsicher sind - die Grundlage für jede spätere
    Eskalation an ein Bildsprachmodell.
    """
    page_range = _parse_range(pages) if pages else None
    run = RunDir(run_dir) if run_dir else None

    def progress(done: int, total: int, page_no: int) -> None:
        if not quiet:
            typer.echo(f"\r  Seite {page_no}  ({done}/{total})", nl=False, err=True)

    try:
        report = analyze_document(
            pdf, dpi=dpi, langs=langs, pages=page_range,
            tessdata_dir=DEFAULT_TESSDATA if DEFAULT_TESSDATA.exists() else None,
            lexicon_path=lexicon, on_progress=None if quiet else progress, run=run,
        )
    except Cancelled as exc:
        typer.echo(f"\nAbgebrochen ({exc}).", err=True)
        raise typer.Exit(0)
    except Exception as exc:
        # Der Lauf muss auch dann einen Endzustand bekommen, wenn er platzt -
        # sonst wartet die Oberflaeche ewig auf einen toten Prozess.
        if run and (state := run.read_state()):
            state.status = FAILED
            state.error = f"{type(exc).__name__}: {exc}"
            run.write_state(state)
            run.append_event(f"Fehlgeschlagen: {state.error}")
        raise

    if not quiet:
        typer.echo("\r" + " " * 40 + "\r", nl=False, err=True)

    _print_report(report)

    if json_out:
        json_out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        typer.echo(f"\nJSON: {json_out}")
    if run:
        (run.path / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


@app.command("jobs")
def cmd_jobs(limit: int = typer.Option(15, help="Wie viele Läufe anzeigen.")) -> None:
    """Bisherige Läufe auflisten."""
    runs = list_runs(limit=limit)
    if not runs:
        typer.echo("Keine Läufe. Ein Lauf entsteht mit --run-dir oder über das Dashboard.")
        return

    typer.echo(f"  {'Lauf':<34} {'Status':<14} {'Fortschritt':>12}  Quelle")
    typer.echo("  " + "─" * 84)
    for run in runs:
        state = run.read_state()
        if state is None:
            continue
        status = run.effective_status()
        progress = f"{state.current}/{state.total}" if state.total else "—"
        typer.echo(f"  {run.id:<34} {_STATUS_TEXT.get(status, status):<14} "
                   f"{progress:>12}  {Path(state.source).name}")


@app.command("cancel")
def cmd_cancel(
    run_id: str = typer.Argument(..., help="Kennung des Laufs, siehe `begutachtung jobs`."),
    force: bool = typer.Option(False, "--force", help="Sofort SIGTERM statt abzuwarten."),
) -> None:
    """Einen laufenden Vorgang anhalten."""
    run = find_run(run_id)
    if run is None:
        typer.echo(f"Kein Lauf mit der Kennung {run_id!r}.", err=True)
        raise typer.Exit(1)

    state = run.read_state()
    if state and state.is_terminal:
        typer.echo(f"Lauf ist bereits {_STATUS_TEXT.get(state.status, state.status)}.")
        return

    run.request_cancel()
    typer.echo("Abbruch angefordert - der Lauf hält nach der aktuellen Seite an.")
    if force and run.kill():
        typer.echo("SIGTERM gesendet.")


@app.command("purge")
def cmd_purge(pdf: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """Zwischengespeicherte Seitenbilder und Ergebnisse löschen.

    Der Cache enthält Seitenbilder aus Patientenakten.
    """
    cache = DocumentCache(pdf)
    size = cache.size_bytes()
    cache.purge()
    typer.echo(f"Gelöscht: {size / 1e6:.1f} MB aus {cache.root}")


@app.command("ui")
def cmd_ui(
    port: int = typer.Option(8000, help="Port."),
    reload: bool = typer.Option(False, "--reload", help="Bei Codeänderungen neu laden."),
) -> None:
    """Das Dashboard starten und im Browser öffnen.

    Bindet bewusst nur an 127.0.0.1: hier liegen Patientendaten auf dem
    Bildschirm, im WLAN sichtbar zu sein wäre eine andere Risikoklasse.
    """
    try:
        import uvicorn
    except ImportError:
        typer.echo("Das Dashboard braucht die UI-Abhängigkeiten:\n"
                   '  pip install -e ".[ui]"', err=True)
        raise typer.Exit(1)

    import os
    os.chdir(REPO_ROOT)  # app.main und config liegen im Projektwurzelverzeichnis
    sys.path.insert(0, str(REPO_ROOT))
    typer.echo(f"Dashboard: http://127.0.0.1:{port}")
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=reload)


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
