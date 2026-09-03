"""Pfade und Grundeinstellungen der Oberflaeche.

Bewusst nur Modulkonstanten, kein pydantic-settings und keine Klassen - so macht
es TangoTrainer auch, und fuer ein Werkzeug mit einem Nutzer ist alles andere
Zeremonie.
"""

from pathlib import Path

BASE_DIR = Path(__file__).parent

APP_DIR = BASE_DIR / "app"
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

TESSDATA_DIR = BASE_DIR / "docker" / "tessdata"
LEXICON_FILE = BASE_DIR / "config" / "lexicon" / "base.txt"
OCR_SCRIPT = BASE_DIR / "ocr_batch.sh"
RUNS_DIR = BASE_DIR / "runs"

# Zuletzt geoeffnete Fallordner. Liegt ausserhalb des Repos, weil die Pfade
# Patientennamen enthalten.
STATE_DIR = Path.home() / ".config" / "begutachtung"
RECENT_FILE = STATE_DIR / "recent.json"

# Vorbelegung der Ordnerauswahl, damit der Normalfall ein Klick ist.
DEFAULT_CASE_ROOT = Path("/mnt/c/Users/carst/Downloads/Gutachten_Eichelberger")

# Nur dieser Rechner. TangoTrainer bindet an 0.0.0.0, weil dort Tanzvideos im
# Heimnetz erreichbar sein sollen - hier liegen Patientendaten auf dem
# Bildschirm, und im WLAN sichtbar zu sein waere eine andere Risikoklasse.
HOST = "127.0.0.1"
PORT = 8000

# Anzeigebreite der Seitenbilder. Die zwischengespeicherten Bilder sind bei
# 400 dpi rund 3300 x 4700 Pixel - die ungefiltert auszuliefern waere mehrere
# Megabyte je Seite.
PAGE_VIEW_WIDTH = 1100
