"""Prueft, ob ein PDF bereits einen nennenswerten Textlayer hat.

Laeuft absichtlich *im* ocrmypdf-Container (dort liegt pdfminer), damit das
Batch-Skript keine Python-Umgebung auf dem Host braucht.

Ausgabe: "1" wenn Text vorhanden, sonst "0".

Der Unterschied ist nicht kosmetisch: bei vorhandenem Text erhaelt --redo-ocr
den Originalinhalt, waehrend --force-ocr die Seiten neu rastert und dabei
scharfen Digitaltext in ein Bild verwandelt. Umgekehrt ist --redo-ocr mit
--deskew nicht kombinierbar, sodass reine Scans ihre Entzerrung verlieren
wuerden. Deshalb wird pro Datei entschieden.
"""

import sys
import warnings

warnings.filterwarnings("ignore")

# Ein reiner Scan liefert 0 Zeichen, eine digital erzeugte Akte einige tausend.
# 500 ueber drei Seiten trennt beides deutlich und laesst Raum fuer Seiten, auf
# denen nur eine Kopfzeile oder eine Seitenzahl als echter Text vorliegt.
MIN_CHARS = 500
PROBE_PAGES = 3


def main() -> int:
    try:
        from pdfminer.high_level import extract_text

        text = extract_text(sys.argv[1], maxpages=PROBE_PAGES) or ""
        print("1" if len(text.strip()) > MIN_CHARS else "0")
    except Exception:
        # Im Zweifel als Scan behandeln - das ist der haeufigere und der
        # verlustfreie Fall, weil --force-ocr auch auf Textseiten funktioniert.
        print("0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
