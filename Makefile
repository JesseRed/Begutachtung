.PHONY: help tessdata lexicon image check test ui clean-cache

TESSDATA_DIR := docker/tessdata
BEST := https://github.com/tesseract-ocr/tessdata_best/raw/main
IMAGE := jbarlow83/ocrmypdf

help:
	@echo "make tessdata  - Tesseract-Sprachmodelle holen (~23 MB, einmalig)"
	@echo "make image     - Docker-Image jbarlow83/ocrmypdf holen"
	@echo "make lexicon   - Deutsche Wortliste aus tessdata erzeugen"
	@echo "make check     - Voraussetzungen pruefen"
	@echo "make test      - Testsuite"
	@echo "make ui        - Dashboard starten (http://127.0.0.1:8000)"
	@echo ""
	@echo "Durchsuchbare PDFs:  ./ocr_batch.sh <verzeichnis>"
	@echo "Seiten bewerten:     begutachtung analyze <datei.pdf>"
	@echo "Dashboard:           make ui"

# tessdata_best ist genauer als die im Image mitgelieferte schnelle Variante.
# Nur deu und eng werden gebraucht: die Dateien werden einzeln in das tessdata-
# Verzeichnis des Images gemountet, osd und die configs bleiben also erhalten.
tessdata: $(TESSDATA_DIR)/deu.traineddata $(TESSDATA_DIR)/eng.traineddata
	@echo "✅ Sprachmodelle vollstaendig in $(TESSDATA_DIR)"

$(TESSDATA_DIR)/%.traineddata:
	@mkdir -p $(TESSDATA_DIR)
	@echo "⬇️  $*.traineddata"
	@curl -fsSL -o $@ "$(BEST)/$*.traineddata"

# Die deutsche Wortliste steckt bereits als DAWG in tessdata_best. Sie hier
# zurueckzuwandeln spart einen externen Download und liefert genau den
# Wortschatz, den Tesseract selbst kennt.
lexicon: config/lexicon/base.txt

config/lexicon/base.txt: $(TESSDATA_DIR)/deu.traineddata $(TESSDATA_DIR)/eng.traineddata
	@mkdir -p config/lexicon
	@echo "Wortliste aus tessdata erzeugen..."
	@docker run --rm -v "$(PWD)/$(TESSDATA_DIR):/td:ro" --entrypoint bash $(IMAGE) -c '\
		cd /tmp; \
		for l in deu eng; do \
			combine_tessdata -u /td/$$l.traineddata $$l. >/dev/null 2>&1; \
			dawg2wordlist $$l.lstm-unicharset $$l.lstm-word-dawg $$l.txt >/dev/null 2>&1; \
		done; cat deu.txt eng.txt' \
		| tr 'A-ZÄÖÜ' 'a-zäöü' | sort -u > $@
	@echo "✅ $$(wc -l < $@) Wörter in $@"

test:
	python -m pytest -q

ui:
	python run.py

image:
	docker pull $(IMAGE)

check:
	@printf 'Docker:      '; docker --version 2>/dev/null || echo "FEHLT"
	@printf 'OCR-Image:   '; docker image inspect $(IMAGE) >/dev/null 2>&1 && echo "vorhanden" || echo "FEHLT - make image"
	@printf 'tessdata:    '; test -f $(TESSDATA_DIR)/deu.traineddata && echo "vorhanden" || echo "FEHLT - make tessdata"

clean-cache:
	rm -rf ~/.cache/begutachtung
