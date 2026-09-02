import sys
from pathlib import Path
from PyPDF2 import PdfReader, PdfWriter

def rotate_pdf(input_file: str, pages="even", angles=None):
    """
    input_file : str
        Pfad zur Eingabedatei
    pages : "even" | "odd" | "all" | list[int]
        Welche Seiten rotiert werden sollen
        - "even"  -> nur gerade Seiten (2,4,6,…)
        - "odd"   -> nur ungerade Seiten (1,3,5,…)
        - "all"   -> alle Seiten
        - [2, 5, 7] -> nur diese Seiten
    angles : list[int] | int | None
        Rotationswinkel in Grad (90, 180, 270)
        - int  -> alle gewählten Seiten gleich rotieren
        - list -> pro Seite ein Winkel, muss gleich lang sein wie pages-Liste
    """

    input_path = Path(input_file)
    if not input_path.exists():
        print(f"Datei nicht gefunden: {input_path}")
        sys.exit(1)

    output_path = input_path.with_name(input_path.stem + "_rotated.pdf")

    reader = PdfReader(str(input_path))
    writer = PdfWriter()

    for i, page in enumerate(reader.pages, start=1):
        rotate_this_page = False
        angle = 0

        # Festlegen, ob diese Seite rotiert werden soll
        if pages == "all":
            rotate_this_page = True
        elif pages == "even" and i % 2 == 0:
            rotate_this_page = True
        elif pages == "odd" and i % 2 == 1:
            rotate_this_page = True
        elif isinstance(pages, list) and i in pages:
            rotate_this_page = True

        # Winkel bestimmen
        if rotate_this_page:
            if isinstance(angles, int):
                angle = angles
            elif isinstance(angles, list):
                if isinstance(pages, list):
                    try:
                        idx = pages.index(i)
                        angle = angles[idx]
                    except (ValueError, IndexError):
                        pass
                else:
                    # wenn Liste, aber pages = all/even/odd
                    try:
                        idx = (i - 1) if pages == "all" else (i // 2 if pages == "even" else (i - 1) // 2)
                        angle = angles[idx]
                    except IndexError:
                        pass

        if angle != 0:
            page.rotate(angle)

        writer.add_page(page)

    with open(output_path, "wb") as f:
        writer.write(f)

    print(f"Fertig! Neue Datei: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Verwendung:")
        print("  python rotate_pdf.py <datei.pdf> [pages] [angle]")
        print("Beispiele:")
        print("  python rotate_pdf.py input.pdf even 180")
        print("  python rotate_pdf.py input.pdf all 90")
        print("  python rotate_pdf.py input.pdf '[2,4,6]' '[90,180,270]'")
        sys.exit(1)

    input_file = sys.argv[1]

    pages_arg = sys.argv[2] if len(sys.argv) > 2 else "even"
    angle_arg = sys.argv[3] if len(sys.argv) > 3 else 180

    # pages verarbeiten
    if pages_arg.lower() in ["all", "even", "odd"]:
        pages = pages_arg.lower()
    else:
        pages = eval(pages_arg)  # z.B. "[2,4,6]"

    # angle verarbeiten
    try:
        angles = int(angle_arg)
    except ValueError:
        angles = eval(angle_arg)  # z.B. "[90,180,270]"

    rotate_pdf(input_file, pages=pages, angles=angles)
