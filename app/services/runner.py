"""Läufe starten - als abgelöster Unterprozess, nicht als Thread.

Die Oberfläche ruft die Pipeline nie direkt auf. Sie startet denselben Befehl,
den der Nutzer auch tippen könnte, und liest danach nur noch Dateien. Das kostet
kaum mehr Code und bringt: der Lauf überlebt einen Neustart von uvicorn (das mit
`reload=True` läuft und Threads bei jedem Dateispeichern töten würde), er ist mit
`ps` sichtbar und vom Terminal aus abbrechbar, und es gibt genau einen Codepfad
statt eines privilegierten für die Oberfläche.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from config import LEXICON_FILE, OCR_SCRIPT, RUNS_DIR

from begutachtung.runstate import RunDir


def _spawn(run: RunDir, args: list[str], cwd: Path) -> RunDir:
    log = open(run.path / "worker.log", "ab")
    proc = subprocess.Popen(
        args, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,   # überlebt einen Neustart des Servers
    )
    run.write_pid(proc.pid)
    run.append_event("Gestartet: " + " ".join(args[:6]) + " …")
    return run


def start_analyze(pdf: Path, dpi: int = 400, pages: str = "",
                  lexicon: bool = True) -> RunDir:
    config = {"pdf": str(pdf), "dpi": dpi, "pages": pages, "lexicon": lexicon}
    run = RunDir.create("analyze", pdf, config, root=RUNS_DIR)

    args = [sys.executable, "-m", "begutachtung.cli", "analyze", str(pdf),
            "--dpi", str(dpi), "--run-dir", str(run.path), "--quiet"]
    if pages:
        args += ["--pages", pages]
    if lexicon and LEXICON_FILE.exists():
        args += ["--lexicon", str(LEXICON_FILE)]

    return _spawn(run, args, cwd=Path(__file__).resolve().parents[2])


def start_ocr(folder: Path) -> RunDir:
    """Durchsuchbare PDFs erzeugen - derselbe Mechanismus, anderer Befehl.

    ocr_batch.sh meldet keinen Seitenfortschritt, deshalb bleibt `total` bei 0;
    die Oberfläche zeigt dann das Protokoll statt eines Balkens.
    """
    run = RunDir.create("ocr", folder, {"folder": str(folder)}, root=RUNS_DIR)
    return _spawn(run, ["bash", str(OCR_SCRIPT), str(folder)], cwd=folder)
