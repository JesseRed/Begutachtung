# Begutachtung

Werkzeuge zur Aufbereitung gescannter Akten für medizinische Gutachten: OCR, Seiten drehen,
Seitenbereiche ausschneiden — und eine Seitenanalyse, die zeigt, welche Seiten unsicher erkannt
wurden und nachgeprüft werden müssen.

## Einrichtung

```bash
make check                       # zeigt, was fehlt
make image                       # Docker-Image holen        (einmalig, ~1 GB)
make tessdata                    # Sprachmodelle holen       (einmalig, ~23 MB)
make lexicon                     # deutsche Wortliste bauen  (einmalig, aus tessdata)

conda env create -f environment.yml
conda activate ocr_env
pip install -e ".[ui]"           # Befehl `begutachtung` und das Dashboard
```

Die OCR läuft komplett in Docker. Die conda-Umgebung wird nur für die PDF-Bearbeitung gebraucht.

## Dashboard

```bash
make ui          # oder: begutachtung ui
```

Dann `http://127.0.0.1:8000` im Browser öffnen. Es bindet **nur an diesen
Rechner** — hier liegen Patientendaten auf dem Bildschirm, im WLAN sichtbar zu
sein wäre eine andere Risikoklasse.

Vier Ansichten:

- **Fälle** — Fallordner öffnen (Pfad eingeben oder aus der Liste wählen).
- **Fall** — die PDFs des Ordners, je Datei Seitenzahl und Analysestand. Hier
  wird ein Lauf gestartet oder ein durchsuchbares PDF erzeugt. Die
  Engine-Matrix zeigt, welche Erkennung für welche Seitenart läuft; lokales
  Bildmodell und Claude sind sichtbar, aber gesperrt, weil noch nicht gebaut.
- **Lauf** — Fortschritt in Echtzeit, abbrechbar. Ein Browser-Refresh verliert
  nichts, und ein Neustart des Servers hält den Lauf nicht an: er läuft als
  eigener Prozess, den auch `begutachtung jobs` sieht.
- **Prüfen** — das Herzstück. Seiten schlechteste zuerst, links das Seitenbild,
  rechts die erkannten Zeilen mit ihrer Konfidenz. Eine Zeile anklicken,
  korrigieren, Enter.

### Korrigieren baut den Referenzsatz

Jede Korrektur in der Prüfansicht wird nach `eval/gold/<digest>/lines.jsonl`
geschrieben — mit erkannter Lesart, richtiger Lesart, Bildausschnitt und
Konfidenz. Das ist genau das Material, mit dem sich später messen lässt, ob ein
Handschriftmodell etwas taugt. Es entsteht bei der Durchsicht, die ohnehin
anfällt; ein separater Nachmittag Tipparbeit entfällt.

`eval/gold/` ist von git ausgeschlossen, weil es Patiententext enthält.

## Die zwei Wege

**`./ocr_batch.sh`** verarbeitet einen ganzen Ordner und erzeugt durchsuchbare PDFs. Das ist der
Weg, wenn du am Ende Dokumente brauchst.

**`begutachtung analyze`** geht seitenweise vor und sagt dir, *welchen* Seiten du nicht trauen
solltest. Das ist der Weg, wenn du wissen willst, wo du nachlesen musst.

### Durchsuchbare PDFs erzeugen

```bash
# erzeugt OCR_<name>.pdf (durchsuchbar) und OCR_<name>.txt (Rohtext)
./ocr_batch.sh ~/Akten/Fall_Mueller

# zusätzliche Argumente gehen an ocrmypdf durch
./ocr_batch.sh . --oversample 600
```

Einstellbar über Umgebungsvariablen: `OCR_JOBS` (Standard 8), `OCR_LANGS` (`deu+eng`),
`OCR_OVERSAMPLE` (400).

### Seiten bewerten

```bash
begutachtung inspect Akte.pdf                    # Seitenzahl, Textlayer, gewählter Modus
begutachtung analyze Akte.pdf --lexicon config/lexicon/base.txt
begutachtung analyze Akte.pdf --pages 40-80 --json bericht.json
begutachtung purge Akte.pdf                      # Zwischenspeicher der Akte löschen
```

Ausgabe je Seite: Klasse, Wortzahl, Tesseract-Konfidenz, Lexikontreffer und die Begründung.
Seiten mit `!` brauchen eine zweite Meinung.

```
  Seite  Klasse        Wörter   Konf    Lex  Bewertung
      6  druck            119   0.94    98%  sauberer Druck, hohe Konfidenz
     11  degradiert       191   0.78    87%  unauffällig
     14! degradiert       122   0.89    70%  Lexikontreffer 70%
```

Der erste Lauf rastert und erkennt jede Seite (~3–4 s/Seite), spätere Läufe kommen aus dem
Zwischenspeicher (~0,1 s/Seite). Der liegt unter `~/.cache/begutachtung/` und enthält
Seitenbilder aus Patientenakten — `begutachtung purge` löscht ihn.

### Seiten drehen, Bereiche ausschneiden

```bash
python rotate_pdf.py Akte.pdf                    # gerade Seiten, 180 Grad
python rotate_pdf.py Akte.pdf "[2,4,6]" "[90,180,270]"
python extractor.py                              # Bereiche laut extract_list.csv
```

`extract_list.csv` hat die Spalten `page_range,input_pdf,output_pdf`; Seitenbereiche sind
1-basiert und einschließlich. `extract_list_example.csv` zeigt das Format.

## Wie die Bewertung zustande kommt

Zwei Signale, die sich ergänzen statt sich zu doppeln:

**Tesseracts Wortkonfidenz** — die Selbsteinschätzung der Erkennung. Nützlich, aber unvollständig:
auf zerfallenem Text meldet Tesseract oft hohe Sicherheit für Zeichenfolgen, die keine Wörter sind.

**Der Lexikontreffer** — wie viele der erkannten Wörter überhaupt deutsche Wörter sind. Die
Wortliste stammt aus `tessdata_best` selbst (`make lexicon` wandelt sie zurück, 237 000 Einträge,
kein externer Download). Deutsche Komposita werden zerlegt, sonst fielen korrekte Wörter wie
*Berufsgenossenschaft* durch und die halbe Akte würde grundlos auffallen.

An 20 echten Aktenseiten gemessen: eine Seite hatte Wortkonfidenz 0,89 — also scheinbar sauber —
bei nur 70 % Lexikontreffer. Über die Konfidenz allein wäre sie durchgerutscht. Genau deshalb
stehen beide Spalten in der Tabelle.

Die Schwellen sind an denselben 20 Seiten kalibriert: unauffällige Seiten liegen bei 83–94 %
Lexikontreffer, erkennbar kaputte bei 4–70 %.

## Was die OCR macht

Pro Datei wird entschieden: PDFs mit vorhandenem Textlayer werden ergänzt (`--redo-ocr`,
Originalinhalt bleibt erhalten), reine Scans werden entzerrt, gerade gedreht, gesäubert, auf
400 dpi hochgerechnet und dann erkannt. Erkennungssprachen sind Deutsch **und** Englisch, weil
medizinisches Deutsch voller englischer Abkürzungen steckt.

Gemessen an 20 echten Aktenseiten gegenüber der Konfiguration davor: mittlere Wortkonfidenz
75,3 % → 79,2 %, erkannte Wörter +6,7 %, besser auf 15 von 20 Seiten. Der Gewinn steckt fast
vollständig in den schlecht gescannten Seiten (schlechteste Seite: 45,8 % → 60,2 %).

## Grenzen

**Handschrift wird nicht erkannt.** Tesseract liegt auf Handschrift bei etwa 45 %
Zeichengenauigkeit. Ausgefüllte Formulare und Ankreuzfelder brauchen ein Bildsprachmodell — das
ist der nächste Ausbauschritt, siehe unten.

**Die Wortkonfidenz ist eine Selbsteinschätzung, kein Messwert.** Ein belastbarer Fehlerwert (CER)
braucht einen korrigierten Referenzsatz. Der wächst jetzt beim Prüfen mit — ausgewertet wird er
noch nicht.

**Die Seitenklassifikation kennt bisher nur `druck`, `degradiert`, `bild` und `leer`.** Formulare,
Handschrift und Tabellen zu unterscheiden braucht Strukturanalyse mit OpenCV und kommt später;
bis dahin landen sie in `degradiert` und fallen über Konfidenz oder Lexikon auf.

## Noch nicht gebaut

**Es gibt bisher nur eine Erkennung: Tesseract.** Im Dashboard sind die Spalten für ein lokales
Bildsprachmodell (Qwen3-VL über llama.cpp) und für Claude sichtbar, aber gesperrt. Solange verlässt
kein Akteninhalt diesen Rechner.

Ebenfalls offen: das Zusammenführen mehrerer Lesarten, die Freigabeansicht vor dem ersten
ausgehenden Aufruf, und die Auswertung des Referenzsatzes (CER/WER).

Der vollständige Plan mit Reihenfolge und Begründungen liegt unter
`~/.claude/plans/ich-moechte-das-ocr-twinkling-rocket.md`.

## Datenschutz

Akten enthalten Patientendaten. `.gitignore` schließt `*.pdf`, alle `OCR_*`-Ergebnisse und
`eval/gold/` aus — diese Regel bitte nicht aufweichen. Der Zwischenspeicher unter
`~/.cache/begutachtung/` enthält Seitenbilder und wird mit `begutachtung purge <datei>` gelöscht.

Solange kein Online-Modell angebunden ist, verlässt kein Akteninhalt den Rechner: OCR läuft in
einem lokalen Container, die Analyse in Python.

## Entwicklung

```bash
make test            # pytest (100 Tests)
make check           # Voraussetzungen
python run.py        # Dashboard mit automatischem Neuladen
```

Läufe vom Terminal aus:

```bash
begutachtung jobs                    # laufende und vergangene Läufe
begutachtung cancel <lauf-kennung>   # anhalten
```

Ein Lauf ist ein Verzeichnis unter `runs/` mit `state.json` und `events.jsonl`.
Deshalb sehen Dashboard und Terminal dasselbe, und ein Lauf überlebt den
Neustart des Servers.
