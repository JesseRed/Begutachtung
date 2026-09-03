"""Tesseract-Engine ueber das ocrmypdf-Docker-Image.

Warum TSV und nicht ocrmypdfs `--sidecar`: der Sidecar liefert nur Text. Fuer den
Textlayer, die Eskalationsentscheidung und den Review-Report brauchen wir
Wortboxen und Wortkonfidenzen, und die gibt es nur, wenn man tesseract direkt
aufruft. Das Image bringt tesseract mit, also kostet das keine zusaetzliche
Abhaengigkeit - nur einen anderen Entrypoint.

TSV-Struktur: Spalte `level` ist 1=Seite, 2=Block, 3=Absatz, 4=Zeile, 5=Wort.
Zeilen (level 4) tragen eine Box, aber conf=-1; die Zeilenkonfidenz wird deshalb
aus den zugehoerigen Woertern gemittelt.
"""

from __future__ import annotations

import csv
import io
import shutil
import subprocess
import time
from pathlib import Path

from .base import BBox, EngineInfo, Estimate, Line, PageResult, Word

IMAGE = "jbarlow83/ocrmypdf"
_LEVEL_LINE = 4
_LEVEL_WORD = 5


class TesseractUnavailable(RuntimeError):
    pass


class TesseractEngine:
    """OCR einer Seite als Bilddatei.

    Die einzige Engine mit `provides_geometry=True`: nur sie liefert Wortboxen,
    auf die sich der Textlayer und der Review-Report stuetzen koennen.
    """

    def __init__(
        self,
        langs: str = "deu+eng",
        psm: int = 3,
        tessdata_dir: Path | None = None,
        image: str = IMAGE,
    ) -> None:
        self.langs = langs
        self.psm = psm
        self.image = image
        self.tessdata_dir = Path(tessdata_dir) if tessdata_dir else None
        self._image_tessdata: str | None = None
        self.info = EngineInfo(
            name="tesseract",
            is_local=True,
            provides_geometry=True,
            model_id="tessdata_best" if tessdata_dir else "tessdata_fast",
            version="5.5.1",
        )
        # Gemessen auf 20 echten Aktenseiten bei 400 dpi; wird vom Scheduler
        # nach den ersten Seiten eines Laufs ueberschrieben.
        self.seconds_per_page = 2.5

    # ---------------------------------------------------------------- Docker

    @staticmethod
    def _docker() -> str:
        exe = shutil.which("docker")
        if not exe:
            raise TesseractUnavailable("docker nicht im PATH")
        return exe

    def _image_tessdata_dir(self) -> str:
        """Wo das Image seine Sprachdateien hat.

        Wird abgefragt statt hartkodiert, weil sich der Pfad mit der
        tesseract-Hauptversion aendert (.../tesseract-ocr/5/tessdata/).
        """
        if self._image_tessdata is None:
            out = subprocess.run(
                [self._docker(), "run", "--rm", "--entrypoint", "tesseract", self.image,
                 "--list-langs"],
                capture_output=True, text=True, timeout=120,
            )
            first = (out.stdout or out.stderr).splitlines()[:1]
            path = ""
            if first and '"' in first[0]:
                path = first[0].split('"')[1]
            self._image_tessdata = path.rstrip("/") or "/usr/share/tesseract-ocr/5/tessdata"
        return self._image_tessdata

    def _mounts(self, image_path: Path) -> list[str]:
        args = ["-v", f"{image_path.parent}:/data:ro", "-w", "/data"]
        if self.tessdata_dir and (self.tessdata_dir / "deu.traineddata").exists():
            target = self._image_tessdata_dir()
            for lang in ("deu", "eng"):
                src = self.tessdata_dir / f"{lang}.traineddata"
                if src.exists():
                    # Einzeln einhaengen statt TESSDATA_PREFIX zu setzen: letzteres
                    # ersetzt das Verzeichnis komplett und nimmt tesseract die
                    # Konfigurationsdateien in configs/ (hocr, tsv, txt).
                    args += ["-v", f"{src}:{target}/{lang}.traineddata:ro"]
        return args

    # ------------------------------------------------------------------- API

    def run(self, image_path: str | Path, page: int = 1) -> PageResult:
        path = Path(image_path).resolve()
        if not path.exists():
            raise FileNotFoundError(path)

        started = time.monotonic()
        proc = subprocess.run(
            [self._docker(), "run", "--rm", *self._mounts(path),
             "--entrypoint", "tesseract", self.image,
             path.name, "stdout", "-l", self.langs, "--psm", str(self.psm), "tsv"],
            capture_output=True, text=True, timeout=600,
        )
        elapsed = time.monotonic() - started

        if proc.returncode != 0:
            raise TesseractUnavailable(
                f"tesseract fehlgeschlagen (rc={proc.returncode}): {proc.stderr.strip()[:400]}"
            )

        lines = parse_tsv(proc.stdout)
        return PageResult(
            engine=self.info.name,
            page=page,
            lines=lines,
            seconds=elapsed,
            meta={"langs": self.langs, "psm": self.psm,
                  "tessdata": "best" if self.tessdata_dir else "image"},
        )

    def available(self) -> tuple[bool, str]:
        try:
            docker = self._docker()
        except TesseractUnavailable as exc:
            return False, str(exc)
        out = subprocess.run([docker, "image", "inspect", self.image],
                             capture_output=True, timeout=60)
        if out.returncode != 0:
            return False, f"Docker-Image {self.image} fehlt - `make image`"
        if self.tessdata_dir and not (self.tessdata_dir / "deu.traineddata").exists():
            return True, "läuft, aber ohne tessdata_best - `make tessdata`"
        return True, "bereit"

    def estimate(self, n_pages: int) -> Estimate:
        return Estimate(seconds=n_pages * self.seconds_per_page)


def parse_tsv(tsv: str) -> list[Line]:
    """TSV in Zeilen mit Woertern umwandeln.

    Als eigenstaendige Funktion, damit sie ohne Docker testbar ist.
    """
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    # Zeilen werden ueber (block, par, line) identifiziert - line_num allein ist
    # nur innerhalb eines Absatzes eindeutig.
    boxes: dict[tuple[int, int, int], BBox] = {}
    words: dict[tuple[int, int, int], list[Word]] = {}
    order: list[tuple[int, int, int]] = []

    for row in reader:
        try:
            level = int(row["level"])
            key = (int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
            bbox = BBox(int(row["left"]), int(row["top"]), int(row["width"]), int(row["height"]))
        except (KeyError, TypeError, ValueError):
            continue

        if level == _LEVEL_LINE:
            boxes[key] = bbox
            if key not in order:
                order.append(key)
        elif level == _LEVEL_WORD:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            try:
                conf = float(row["conf"])
            except (KeyError, TypeError, ValueError):
                conf = -1.0
            words.setdefault(key, []).append(
                Word(text=text, bbox=bbox, conf=conf / 100.0 if conf >= 0 else None)
            )
            if key not in order:
                order.append(key)

    result: list[Line] = []
    for key in order:
        line_words = words.get(key, [])
        if not line_words:
            continue  # Zeilenbox ohne erkannte Woerter - nichts zu berichten
        line = Line(
            text=" ".join(w.text for w in line_words),
            bbox=boxes.get(key),
            words=line_words,
        )
        line.conf = line.mean_word_conf
        result.append(line)
    return result
