"""Inhaltsadressierter Artefakt-Cache.

Der Cache ist der Grund, warum ein zweiter Lauf mit anderem Budget billig ist -
und bei der Cloud-Engine auch, warum er nichts kostet. Die Schluessel enthalten
Engine, Modellversion und die Parameter, sodass eine DPI-Aenderung Raster und
Engine-Ergebnisse invalidiert, eine geaenderte Reconciliation-Gewichtung aber
nur die zusammengefuehrten Ergebnisse.

Er liegt bewusst ausserhalb des Repos: er enthaelt Seitenbilder aus
Patientenakten. `begutachtung purge` loescht ihn.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

CACHE_ROOT = Path.home() / ".cache" / "begutachtung"


def file_digest(path: str | Path, chunk: int = 1 << 20) -> str:
    """SHA256 der Datei, gekuerzt. Inhaltsadressiert statt pfadadressiert, damit
    eine umbenannte oder verschobene Akte ihren Cache behaelt."""
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(chunk):
            h.update(block)
    return h.hexdigest()[:12]


def params_hash(params: dict[str, Any]) -> str:
    """Stabiler Hash ueber Parameter. sort_keys ist wesentlich - ohne das
    invalidiert eine andere Einfuegereihenfolge den Cache stillschweigend."""
    blob = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:8]


class DocumentCache:
    """Artefakte eines PDF."""

    def __init__(self, pdf_path: str | Path, root: Path = CACHE_ROOT) -> None:
        self.pdf_path = Path(pdf_path)
        self.digest = file_digest(self.pdf_path)
        self.root = Path(root) / self.digest
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- Struktur

    def page_dir(self, page: int) -> Path:
        d = self.root / "pages" / f"{page:04d}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def image_path(self, page: int, variant: str = "raw", dpi: int = 400) -> Path:
        return self.page_dir(page) / f"{variant}.dpi{dpi}.png"

    def result_path(self, page: int, engine: str, version: str, params: dict[str, Any]) -> Path:
        return self.page_dir(page) / f"eng.{engine}@{version}.{params_hash(params)}.json"

    # ---------------------------------------------------------------- Zugriff

    def load_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Ein halb geschriebenes Artefakt darf den Lauf nicht anhalten -
            # es wird einfach neu berechnet.
            return None

    def save_json(self, path: Path, data: dict[str, Any]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)  # atomar, damit ein Abbruch keine Ruine hinterlaesst
        return path

    def write_meta(self, page_count: int, extra: dict[str, Any] | None = None) -> None:
        self.save_json(self.root / "meta.json", {
            "source": str(self.pdf_path),
            "digest": self.digest,
            "page_count": page_count,
            **(extra or {}),
        })

    def size_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())

    def purge(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
