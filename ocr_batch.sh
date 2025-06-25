#!/bin/bash

INPUT_DIR=~/Code/Begutachtung

# Activate safety: stop on error
set -e

echo "📄 Starting OCR processing in $INPUT_DIR..."

for input_file in "$INPUT_DIR"/*.pdf; do
    filename=$(basename "$input_file")
    output_file="OCR_${filename}"

    echo "🔍 Processing: $filename → $output_file"

    docker run --rm -v "$INPUT_DIR":/home/documents -u $(id -u):$(id -g) \
        jbarlow83/ocrmypdf \
        -l deu "/home/documents/$filename" "/home/documents/$output_file"

    echo "✅ Done: $output_file"
done

echo "🎉 All files processed!"
