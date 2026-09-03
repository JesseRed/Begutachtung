# Begutachtung

Werkzeuge zur Aufbereitung gescannter Akten für medizinische Gutachten: OCR, Seiten drehen,
Seitenbereiche als Einzeldokumente ausschneiden.

## Einrichtung

```bash
make check       # zeigt, was fehlt
make image       # Docker-Image holen (einmalig, ~1 GB)
make tessdata    # Tesseract-Sprachmodelle holen (einmalig, ~23 MB)

conda env create -f environment.yml
conda activate ocr_env
```

Die OCR läuft komplett in Docker. Die conda-Umgebung wird nur für die PDF-Bearbeitung gebraucht.

## Verwendung

```bash
# 1. OCR - erzeugt OCR_<name>.pdf (durchsuchbar) und OCR_<name>.txt (Rohtext)
./ocr_batch.sh ~/Akten/Fall_Mueller

# 2. Falls der Einzug jede zweite Seite auf dem Kopf gescannt hat
python rotate_pdf.py Akte.pdf              # gerade Seiten, 180 Grad
python rotate_pdf.py Akte.pdf "[2,4,6]" "[90,180,270]"

# 3. Seitenbereiche laut extract_list.csv ausschneiden
python extractor.py
```

`extract_list.csv` hat die Spalten `page_range,input_pdf,output_pdf`; Seitenbereiche sind
1-basiert und einschließlich. `extract_list_example.csv` zeigt das Format.

## Was die OCR macht

Pro Datei wird entschieden: PDFs mit vorhandenem Textlayer werden ergänzt (`--redo-ocr`,
Originalinhalt bleibt erhalten), reine Scans werden entzerrt, gerade gedreht, gesäubert, auf
400 dpi hochgerechnet und dann erkannt. Erkennungssprachen sind Deutsch und Englisch, weil
medizinisches Deutsch voller englischer Abkürzungen steckt.

Gemessen an 20 echten Aktenseiten gegenüber der vorherigen Konfiguration: mittlere Wortkonfidenz
75,3 % → 79,2 %, erkannte Wörter +6,7 %. Der Gewinn steckt fast vollständig in den schlecht
gescannten Seiten.

Einstellbar über Umgebungsvariablen: `OCR_JOBS` (Standard 8), `OCR_LANGS` (`deu+eng`),
`OCR_OVERSAMPLE` (400). Zusätzliche Argumente werden an `ocrmypdf` durchgereicht:

```bash
./ocr_batch.sh . --oversample 600
```

## Grenzen

**Handschrift wird nicht erkannt.** Tesseract liegt auf Handschrift bei etwa 45 % Zeichen­genauigkeit;
ausgefüllte Formulare und Ankreuzfelder brauchen ein Bildsprachmodell. Das ist der nächste
Ausbauschritt.

## Datenschutz

Akten enthalten Patientendaten. `.gitignore` schließt `*.pdf` und alle `OCR_*`-Ergebnisse aus —
diese Regel bitte nicht aufweichen.
