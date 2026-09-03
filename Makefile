.PHONY: help tessdata image check clean-cache

TESSDATA_DIR := docker/tessdata
BEST := https://github.com/tesseract-ocr/tessdata_best/raw/main
IMAGE := jbarlow83/ocrmypdf

help:
	@echo "make tessdata  - Tesseract-Sprachmodelle holen (~23 MB, einmalig)"
	@echo "make image     - Docker-Image jbarlow83/ocrmypdf holen"
	@echo "make check     - Voraussetzungen pruefen"
	@echo ""
	@echo "OCR laufen lassen:  ./ocr_batch.sh <verzeichnis>"

# tessdata_best ist genauer als die im Image mitgelieferte schnelle Variante.
# Nur deu und eng werden gebraucht: die Dateien werden einzeln in das tessdata-
# Verzeichnis des Images gemountet, osd und die configs bleiben also erhalten.
tessdata: $(TESSDATA_DIR)/deu.traineddata $(TESSDATA_DIR)/eng.traineddata
	@echo "✅ Sprachmodelle vollstaendig in $(TESSDATA_DIR)"

$(TESSDATA_DIR)/%.traineddata:
	@mkdir -p $(TESSDATA_DIR)
	@echo "⬇️  $*.traineddata"
	@curl -fsSL -o $@ "$(BEST)/$*.traineddata"

image:
	docker pull $(IMAGE)

check:
	@printf 'Docker:      '; docker --version 2>/dev/null || echo "FEHLT"
	@printf 'OCR-Image:   '; docker image inspect $(IMAGE) >/dev/null 2>&1 && echo "vorhanden" || echo "FEHLT - make image"
	@printf 'tessdata:    '; test -f $(TESSDATA_DIR)/deu.traineddata && echo "vorhanden" || echo "FEHLT - make tessdata"

clean-cache:
	rm -rf ~/.cache/begutachtung
