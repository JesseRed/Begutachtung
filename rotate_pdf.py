"""Seiten eines PDF drehen - typisch fuer Akten, bei denen der Einzug jede
zweite Seite auf dem Kopf eingescannt hat.

Verwendung:
  python rotate_pdf.py <datei.pdf> [seiten] [winkel]

Beispiele:
  python rotate_pdf.py Akte.pdf                    # Standard: gerade Seiten, 180 Grad
  python rotate_pdf.py Akte.pdf all 90
  python rotate_pdf.py Akte.pdf odd 270
  python rotate_pdf.py Akte.pdf "[2,4,6]" "[90,180,270]"

Ausgabe: <name>_rotated.pdf neben der Eingabedatei.
"""

import json
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter

Pages = str | list[int]


def select_pages(spec: Pages, page_count: int) -> list[int]:
    """Die zu drehenden Seitennummern (1-basiert), in aufsteigender Reihenfolge.

    Diese Funktion ist der Grund, warum es hier keine Index-Arithmetik mehr gibt:
    Wer die Seitenliste einmal explizit aufbaut, kann die Winkel danach schlicht
    per zip() zuordnen. Die alte Fassung rechnete den Winkel-Index aus der
    Seitennummer zurueck und lag im even-Zweig um eins daneben (Seite 2 griff auf
    Winkel 1 statt 0 zu).
    """
    all_pages = range(1, page_count + 1)
    if isinstance(spec, list):
        return [p for p in sorted(set(spec)) if 1 <= p <= page_count]
    if spec == "all":
        return list(all_pages)
    if spec == "even":
        return [p for p in all_pages if p % 2 == 0]
    if spec == "odd":
        return [p for p in all_pages if p % 2 == 1]
    raise ValueError(f"Unbekannte Seitenauswahl: {spec!r}")


def resolve_angles(angles: int | list[int], n_pages: int) -> list[int]:
    """Einen Winkel je ausgewaehlter Seite."""
    if isinstance(angles, int):
        resolved = [angles] * n_pages
    else:
        if len(angles) != n_pages:
            raise ValueError(
                f"{len(angles)} Winkel fuer {n_pages} ausgewaehlte Seiten - "
                "die Listen muessen gleich lang sein."
            )
        resolved = list(angles)

    for angle in resolved:
        if angle % 90 != 0:
            raise ValueError(f"Winkel muss ein Vielfaches von 90 sein, nicht {angle}.")
    return resolved


def rotate_pdf(
    input_file: str,
    pages: Pages = "even",
    angles: int | list[int] = 180,
) -> Path:
    input_path = Path(input_file)
    if not input_path.exists():
        raise FileNotFoundError(f"Datei nicht gefunden: {input_path}")

    reader = PdfReader(str(input_path))
    selected = select_pages(pages, len(reader.pages))
    angle_for = dict(zip(selected, resolve_angles(angles, len(selected))))

    writer = PdfWriter()
    for number, page in enumerate(reader.pages, start=1):
        angle = angle_for.get(number, 0)
        if angle:
            page.rotate(angle)
        writer.add_page(page)

    output_path = input_path.with_name(input_path.stem + "_rotated.pdf")
    with open(output_path, "wb") as handle:
        writer.write(handle)

    print(f"{len(selected)} von {len(reader.pages)} Seiten gedreht → {output_path}")
    return output_path


def parse_arg(raw: str) -> str | int | list[int]:
    """CLI-Argument deuten. Bewusst json.loads statt eval - das alte Skript hat
    beliebigen Code aus der Kommandozeile ausgefuehrt."""
    if raw.lower() in ("all", "even", "odd"):
        return raw.lower()
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"Nicht interpretierbar: {raw!r} (erwartet z.B. 180 oder [90,180])")
    if isinstance(value, int):
        return value
    if isinstance(value, list) and all(isinstance(v, int) for v in value):
        return value
    raise ValueError(f"Erwartet Zahl oder Liste von Zahlen, nicht {raw!r}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip())
        return 1

    try:
        pages = parse_arg(argv[2]) if len(argv) > 2 else "even"
        angles = parse_arg(argv[3]) if len(argv) > 3 else 180
        if isinstance(pages, int):
            pages = [pages]
        if isinstance(angles, str):
            raise ValueError(f"Winkel muss eine Zahl oder Liste sein, nicht {angles!r}")
        rotate_pdf(argv[1], pages=pages, angles=angles)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
