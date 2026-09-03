"""Das Lauf-Verzeichnis ist der Job.

Kein Thread, kein Job-Objekt im Speicher, keine Datenbank. Ein Lauf ist ein
Verzeichnis mit Dateien; wer wissen will, wie es steht, liest sie.

Das ist kein Purismus, sondern folgt aus zwei Zwaengen. Erstens laeuft der
Webserver mit `reload=True` - jeder Dateispeicherer wuerde einen Worker-Thread
mitten im Lauf toeten. Zweitens gaebe es sonst zwei Codepfade: die Oberflaeche
riefe die Pipeline direkt auf, die Kommandozeile als Unterprozess. Zwei Pfade
heisst, die Oberflaeche haette einen privilegierten Zugang - genau das, was man
nicht will, wenn spaeter die Zusage gilt "ohne Freigabe verlaesst nichts den
Rechner".

Nebenbei faellt ab: der Lauf ueberlebt einen Serverneustart, ist mit `ps`
sichtbar, mit `tail -f` verfolgbar und vom Terminal aus abbrechbar.
"""

from __future__ import annotations

import json
import os
import re
import signal
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

RUNS_ROOT = Path(__file__).resolve().parents[2] / "runs"

STATE_FILE = "state.json"
EVENTS_FILE = "events.jsonl"
CONFIG_FILE = "run.json"
PID_FILE = "worker.pid"
CANCEL_FILE = "CANCEL"

# Interne Schluessel bleiben englisch, die Uebersetzung passiert in der
# Oberflaeche - so bleibt der Zustand greppbar und sprachunabhaengig.
RUNNING = "running"
DONE = "done"
CANCELLED = "cancelled"
FAILED = "failed"
TERMINAL = frozenset({DONE, CANCELLED, FAILED})

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass
class RunState:
    id: str
    kind: str = "analyze"
    """`analyze` oder `ocr` - bestimmt nur die Anzeige, nicht die Mechanik."""
    source: str = ""
    status: str = RUNNING
    phase: str = ""
    current: int = 0
    total: int = 0
    started: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    counters: dict[str, int] = field(default_factory=dict)
    error: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL

    @property
    def percent(self) -> int:
        return int(100 * self.current / self.total) if self.total else 0

    @property
    def elapsed(self) -> float:
        end = self.updated if self.is_terminal else time.time()
        return max(0.0, end - self.started)

    @property
    def eta_seconds(self) -> float | None:
        """Nur hochrechnen, wenn genug Seiten gelaufen sind - eine Restzeit aus
        zwei Messpunkten ist eine Zahl, der man mehr glaubt als sie verdient."""
        if self.is_terminal or self.current < 3 or not self.total:
            return None
        per_page = self.elapsed / self.current
        return per_page * (self.total - self.current)


class RunDir:
    """Ein Lauf-Verzeichnis, von beiden Seiten benutzt: der Worker schreibt,
    die Oberflaeche liest."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    # ------------------------------------------------------------- anlegen

    @classmethod
    def create(cls, kind: str, source: str | Path, config: dict[str, Any] | None = None,
               root: Path = RUNS_ROOT) -> RunDir:
        stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(source).stem)[:40] or "lauf"
        run = cls(Path(root) / f"{stamp}_{stem}")
        run.path.mkdir(parents=True, exist_ok=True)
        run.write_config(config or {})
        run.write_state(RunState(id=run.id, kind=kind, source=str(source)))
        return run

    @property
    def id(self) -> str:
        return self.path.name

    # -------------------------------------------------------------- lesen

    def read_state(self) -> RunState | None:
        data = _read_json(self.path / STATE_FILE)
        if not data:
            return None
        known = {f for f in RunState.__dataclass_fields__}
        return RunState(**{k: v for k, v in data.items() if k in known})

    def read_config(self) -> dict[str, Any]:
        return _read_json(self.path / CONFIG_FILE) or {}

    def tail_events(self, n: int = 30) -> list[dict[str, Any]]:
        f = self.path / EVENTS_FILE
        if not f.exists():
            return []
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # halb geschriebene letzte Zeile - kein Grund anzuhalten
        return out

    # ------------------------------------------------------------ schreiben

    def write_config(self, config: dict[str, Any]) -> None:
        _write_json(self.path / CONFIG_FILE, config)

    def write_state(self, state: RunState) -> None:
        state.updated = time.time()
        _write_json(self.path / STATE_FILE, asdict(state))

    def append_event(self, message: str, **fields: Any) -> None:
        line = json.dumps({"ts": time.time(), "msg": message, **fields}, ensure_ascii=False)
        with open(self.path / EVENTS_FILE, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def write_pid(self, pid: int | None = None) -> None:
        (self.path / PID_FILE).write_text(str(pid or os.getpid()), encoding="utf-8")

    def read_pid(self) -> int | None:
        try:
            return int((self.path / PID_FILE).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    # ------------------------------------------------------------- Abbruch

    def request_cancel(self) -> None:
        (self.path / CANCEL_FILE).touch()

    @property
    def cancel_requested(self) -> bool:
        return (self.path / CANCEL_FILE).exists()

    def kill(self, sig: int = signal.SIGTERM) -> bool:
        """Nachfassen, wenn der Worker nicht von selbst anhaelt."""
        pid = self.read_pid()
        if not pid:
            return False
        try:
            os.kill(pid, sig)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def worker_alive(self) -> bool:
        pid = self.read_pid()
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def effective_status(self) -> str:
        """Der Status, korrigiert um die Wirklichkeit.

        Steht `running` in der Datei, der Prozess ist aber weg, dann hat ihn
        etwas abgeraeumt - ein Neustart der Maschine, ein OOM-Kill. Das als
        `running` anzuzeigen waere eine Luege, auf die der Nutzer wartet.
        """
        state = self.read_state()
        if state is None:
            return FAILED
        if state.status == RUNNING and not self.worker_alive():
            return FAILED
        return state.status


# ------------------------------------------------------------------ Auflisten


def list_runs(root: Path = RUNS_ROOT, limit: int = 50) -> list[RunDir]:
    if not Path(root).exists():
        return []
    dirs = sorted((d for d in Path(root).iterdir() if d.is_dir()), reverse=True)
    return [RunDir(d) for d in dirs[:limit]]


def find_run(run_id: str, root: Path = RUNS_ROOT) -> RunDir | None:
    """Einen Lauf ueber seine Kennung finden.

    Die Kennung kommt aus einer URL, deshalb wird sie gegen ein Muster geprueft
    statt sie an den Pfad zu haengen: `../../etc` waere sonst ein gueltiger Lauf.
    """
    if not _SAFE_ID.match(run_id or "") or set(run_id) <= {"."}:
        return None
    # Erst aufloesen, dann vergleichen. Die lexikalische Pruefung allein reicht
    # nicht: `Path("runs/..").parent` ist lexikalisch `runs` und sieht damit
    # richtig aus, waehrend der Pfad tatsaechlich aus dem Verzeichnis
    # herausfuehrt.
    base = Path(root).resolve()
    path = (base / run_id).resolve()
    if not path.is_dir() or path.parent != base:
        return None
    return RunDir(path)


# ------------------------------------------------------------------- intern


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomar schreiben, damit ein Leser nie eine halbe Datei sieht.

    Die Oberflaeche liest im Sekundentakt waehrend der Worker schreibt - ohne
    os.replace() faengt sie sich regelmaessig einen JSONDecodeError.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
