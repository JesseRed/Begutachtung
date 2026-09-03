"""Was diese Maschine kann.

Eine Prüffunktion für alle Nutzer: die Systemansicht, später `begutachtung
doctor` und `make check`. Nur so gibt es eine Wahrheit statt dreier, die
auseinanderlaufen.

Die Ergebnisse werden kurz zwischengespeichert - `docker image inspect` bei
jedem Seitenaufruf auszuführen macht die Oberfläche träge, und die Antwort
ändert sich selten.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from config import LEXICON_FILE, OCR_SCRIPT, TESSDATA_DIR

CACHE_TTL_SECONDS = 300
OCR_IMAGE = "jbarlow83/ocrmypdf"


@dataclass
class Capability:
    key: str
    label: str
    ok: bool
    detail: str
    hint: str = ""
    """Was zu tun ist, wenn es fehlt - als kopierbarer Befehl."""
    planned: bool = False
    """Nicht kaputt, sondern noch nicht gebaut. Wird anders dargestellt."""


@dataclass
class _Cached:
    at: float = 0.0
    items: list[Capability] = field(default_factory=list)


_cache = _Cached()


def _run(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def probe(force: bool = False) -> list[Capability]:
    if not force and _cache.items and (time.time() - _cache.at) < CACHE_TTL_SECONDS:
        return _cache.items

    items: list[Capability] = []
    docker = shutil.which("docker")

    if docker:
        out = _run([docker, "version", "--format", "{{.Server.Version}}"])
        ok = bool(out and out.returncode == 0)
        version = (out.stdout.strip() if out and out.stdout else "")
        items.append(Capability("docker", "Docker", ok,
                                f"Version {version}" if ok else "läuft nicht",
                                "" if ok else "Docker Desktop starten"))
    else:
        items.append(Capability("docker", "Docker", False, "nicht im PATH",
                                "Docker installieren"))

    image_ok = bool(docker and (o := _run([docker, "image", "inspect", OCR_IMAGE]))
                    and o.returncode == 0)
    items.append(Capability("ocr_image", "OCR-Image", image_ok,
                            OCR_IMAGE if image_ok else "fehlt",
                            "" if image_ok else "make image"))

    deu = TESSDATA_DIR / "deu.traineddata"
    tess_ok = deu.exists()
    items.append(Capability("tessdata", "Sprachmodelle", tess_ok,
                            f"tessdata_best, {deu.stat().st_size // 1_000_000} MB" if tess_ok
                            else "fehlen",
                            "" if tess_ok else "make tessdata"))

    lex_ok = LEXICON_FILE.exists()
    n_words = 0
    if lex_ok:
        try:
            n_words = sum(1 for _ in LEXICON_FILE.open(encoding="utf-8", errors="replace"))
        except OSError:
            lex_ok = False
    items.append(Capability("lexikon", "Wörterliste", lex_ok,
                            f"{n_words:,} Einträge".replace(",", ".") if lex_ok else "fehlt",
                            "" if lex_ok else "make lexicon"))

    items.append(Capability("ocr_script", "ocr_batch.sh", OCR_SCRIPT.exists(),
                            "vorhanden" if OCR_SCRIPT.exists() else "fehlt"))

    # GPU: heute nur informativ. Sie entscheidet später, welche lokalen Modelle
    # überhaupt angeboten werden.
    gpu = _run(["nvidia-smi", "--query-gpu=name,memory.total,compute_cap",
                "--format=csv,noheader"])
    if gpu and gpu.returncode == 0 and gpu.stdout.strip():
        name, mem, cap = (p.strip() for p in gpu.stdout.strip().splitlines()[0].split(","))
        items.append(Capability("gpu", "Grafikkarte", True, f"{name}, {mem}, Compute {cap}"))
    else:
        items.append(Capability("gpu", "Grafikkarte", False, "keine NVIDIA-GPU erkannt"))

    items.append(Capability("local_vlm", "Lokales Bildmodell", False,
                            "noch nicht gebaut", planned=True))
    items.append(Capability("claude", "Claude (Cloud)", False,
                            "noch nicht gebaut", planned=True))

    _cache.at, _cache.items = time.time(), items
    return items


def cache_size_bytes() -> int:
    from begutachtung.cache import CACHE_ROOT
    if not CACHE_ROOT.exists():
        return 0
    return sum(f.stat().st_size for f in CACHE_ROOT.rglob("*") if f.is_file())
