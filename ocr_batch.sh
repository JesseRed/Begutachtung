#!/bin/bash
# OCR fuer gescannte Begutachtungs-Akten.
#
# Verwendung:
#   ./ocr_batch.sh [VERZEICHNIS] [weitere ocrmypdf-Optionen...]
#
# Beispiele:
#   ./ocr_batch.sh                       # aktuelles Verzeichnis
#   ./ocr_batch.sh ~/Akten/Fall_Mueller
#   ./ocr_batch.sh . --oversample 600    # hoehere Aufloesung fuer schlechte Scans
#
# Ausgabe: OCR_<name>.pdf (durchsuchbar) und OCR_<name>.txt (Rohtext) je Eingabedatei.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESSDATA_DIR="$SCRIPT_DIR/docker/tessdata"
IMAGE="jbarlow83/ocrmypdf"
JOBS="${OCR_JOBS:-8}"          # RAM ist der Engpass (15 GB), nicht die 32 Kerne
LANGS="${OCR_LANGS:-deu+eng}"  # medizinisches Deutsch ist voll englischer Abkuerzungen
OVERSAMPLE="${OCR_OVERSAMPLE:-400}"

INPUT_DIR="${1:-.}"
[ $# -gt 0 ] && shift
EXTRA_ARGS=("$@")

INPUT_DIR="$(cd "$INPUT_DIR" 2>/dev/null && pwd)" || {
    echo "Verzeichnis nicht gefunden: ${1:-.}" >&2; exit 1
}

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Docker-Image $IMAGE fehlt. Einmalig holen: make image" >&2
    exit 1
fi

# tessdata_best statt der im Image mitgelieferten schnellen Variante.
# Messung auf synthetisch degradierten Testseiten: mittlere CER 5.4 % -> 4.5 %,
# Median 4.1 % -> 2.7 %, zusammen mit deu+eng. Der Gewinn steckt fast ganz in den
# schlecht gescannten Seiten; bei sehr niedriger Aufloesung kann es leicht schaden.
#
# Die Dateien werden EINZELN eingehaengt statt per TESSDATA_PREFIX auf ein eigenes
# Verzeichnis zu zeigen: TESSDATA_PREFIX ersetzt das Verzeichnis des Images komplett,
# und damit verliert Tesseract die Konfigurationsdateien in configs/ (hocr, txt, tsv).
# Ohne die bricht ocrmypdf mit "Can't open hocr" ab.
TESSDATA_ARGS=()
if [ -f "$TESSDATA_DIR/deu.traineddata" ]; then
    image_tessdata=$(docker run --rm --entrypoint tesseract "$IMAGE" --list-langs 2>&1 \
        | sed -n '1s/.*"\(.*\)".*/\1/p')
    if [ -n "$image_tessdata" ]; then
        for lang in deu eng; do
            [ -f "$TESSDATA_DIR/$lang.traineddata" ] && TESSDATA_ARGS+=(
                -v "$TESSDATA_DIR/$lang.traineddata:${image_tessdata%/}/$lang.traineddata:ro"
            )
        done
    else
        echo "⚠️  Tessdata-Pfad des Images nicht ermittelbar - benutze die Modelle aus dem Image."
    fi
else
    echo "⚠️  $TESSDATA_DIR/deu.traineddata fehlt - benutze die schnelleren Modelle aus dem Image."
    echo "    Holen mit:  make tessdata"
fi

shopt -s nullglob nocaseglob
pdfs=("$INPUT_DIR"/*.pdf)
shopt -u nocaseglob

if [ ${#pdfs[@]} -eq 0 ]; then
    echo "Keine PDFs in $INPUT_DIR"; exit 0
fi

echo "📄 OCR in $INPUT_DIR  (Sprachen: $LANGS, $JOBS parallel, oversample $OVERSAMPLE)"
echo

ok=0; failed=0; skipped=0
failed_files=()

for input_file in "${pdfs[@]}"; do
    filename="$(basename "$input_file")"

    # Eigene Ergebnisse nicht erneut verarbeiten - das alte Skript lief in genau diese Falle.
    case "$filename" in
        OCR_*) skipped=$((skipped+1)); continue ;;
    esac

    output_file="OCR_${filename}"
    sidecar="OCR_${filename%.pdf}.txt"

    if [ -f "$INPUT_DIR/$output_file" ]; then
        echo "⏭️  $filename - $output_file existiert bereits"
        skipped=$((skipped+1)); continue
    fi

    # Hat die Datei schon einen nennenswerten Textlayer? Dann den Originalinhalt
    # erhalten (--redo-ocr) statt die Seiten neu zu rastern. --redo-ocr ist mit
    # --deskew nicht kombinierbar, deshalb sind es zwei getrennte Modi.
    # Die Pruefung laeuft im Container, damit auf dem Host kein Python noetig ist.
    has_text=$(docker run --rm \
        -v "$INPUT_DIR:/data:ro" \
        -v "$SCRIPT_DIR/docker:/helper:ro" \
        --entrypoint python3 "$IMAGE" \
        /helper/detect_text.py "/data/$filename" 2>/dev/null) || has_text=0

    if [ "$has_text" = "1" ]; then
        mode_args=(--redo-ocr)
        mode_label="Textlayer vorhanden -> ergaenzen"
    else
        mode_args=(--force-ocr --deskew --rotate-pages --clean --oversample "$OVERSAMPLE")
        mode_label="reiner Scan -> entzerren + OCR"
    fi

    echo "🔍 $filename → $output_file  ($mode_label)"

    if docker run --rm \
        -v "$INPUT_DIR:/data" -w /data \
        "${TESSDATA_ARGS[@]}" \
        -u "$(id -u):$(id -g)" \
        "$IMAGE" \
        -l "$LANGS" \
        "${mode_args[@]}" \
        --sidecar "$sidecar" \
        --jobs "$JOBS" \
        --output-type pdf \
        "${EXTRA_ARGS[@]}" \
        "$filename" "$output_file"
    then
        echo "✅ $output_file"
        ok=$((ok+1))
    else
        echo "⚠️  Fehlgeschlagen: $filename"
        failed=$((failed+1)); failed_files+=("$filename")
    fi
    echo
done

echo "────────────────────────────────────────"
echo "🎉 $ok erfolgreich, $failed fehlgeschlagen, $skipped übersprungen"
if [ ${#failed_files[@]} -gt 0 ]; then
    echo
    echo "Fehlgeschlagen:"
    printf '  %s\n' "${failed_files[@]}"
    echo
    echo "Bei beschaedigten PDFs hilft oft:  ./ocr_batch.sh \"$INPUT_DIR\" --continue-on-soft-render-error"
fi
[ "$failed" -eq 0 ]
