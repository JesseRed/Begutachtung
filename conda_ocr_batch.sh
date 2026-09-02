#!/bin/bash

# Define input directory
INPUT_DIR=~/Code/Begutachtung

# Load conda
eval "$(conda shell.bash hook)"
conda activate ocr_env

echo "📄 Starting OCR processing in $INPUT_DIR..."

for input_file in "$INPUT_DIR"/*.pdf; do
    filename=$(basename "$input_file")
    output_file="${filename%.pdf}_OCR.pdf"

    echo "🔍 Processing: $filename → $output_file"

    if docker run --rm -v "$INPUT_DIR":/home/documents -u $(id -u):$(id -g) \
        jbarlow83/ocrmypdf \
        -l deu --force-ocr "/home/documents/$filename" "/home/documents/$output_file"; then
        echo "✅ Done: $output_file"
    else
        echo "⚠️  Failed: $filename - skipping"
    fi
done

echo "🎉 All files processed!"
