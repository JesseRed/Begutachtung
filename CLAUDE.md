# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

A small toolbox of standalone scripts for preparing medical/legal case files ("Begutachtung") for review. The typical workflow is a manual pipeline, not an application:

1. **OCR** a scanned case file (`Akte.pdf`) with `ocrmypdf` running in Docker, German language model.
2. **Rotate** pages that were scanned upside down (`rotate_pdf.py`).
3. **Extract** the relevant page ranges into individually named documents (`extractor.py`), driven by a CSV list.

Each step is run by hand, on PDFs that sit loose in the repository root. There is no build, no test suite and no package — the scripts share no code and are not importable modules.

## Environment

Conda environment `ocr_env` (Python 3.10, see `environment.yml`):

```bash
conda env create -f environment.yml   # first time
conda activate ocr_env
```

`environment.yml` pins `pypdf==4.2.0`, but `rotate_pdf.py` imports `PyPDF2` — that dependency is missing from the environment file and must be installed separately (`pip install PyPDF2`), or the script ported to `pypdf`.

OCR itself does not run in the conda environment; it runs in the `jbarlow83/ocrmypdf` Docker image, so a working Docker daemon is required.

## Commands

```bash
# OCR every PDF in the input directory
./conda_ocr_batch.sh      # activates ocr_env, --force-ocr, continues past failures
./ocr_batch.sh            # no conda, set -e, aborts on first failure

# Rotate pages (writes <name>_rotated.pdf next to the input)
python rotate_pdf.py Akte.pdf even 180          # default: even pages, 180°
python rotate_pdf.py Akte.pdf all 90
python rotate_pdf.py Akte.pdf '[2,4,6]' '[90,180,270]'

# Split out the page ranges listed in extract_list.csv
python extractor.py
```

## Things to know before changing these scripts

- **`INPUT_DIR` is hardcoded** to `~/Code/Begutachtung` in both OCR scripts, and it is both the input and the output directory. Re-running an OCR script therefore also picks up the `*_OCR.pdf` files it produced on the previous run.
- **The two OCR scripts differ in output naming** (`OCR_<name>.pdf` vs `<name>_OCR.pdf`) and in failure behaviour. `conda_ocr_batch.sh` is the newer one and the one normally used.
- **`extractor.py` reads `extract_list.csv` from the current working directory** — the filename is hardcoded, not a CLI argument. `extract_list_example.csv` documents the format (`page_range,input_pdf,output_pdf`, 1-based inclusive ranges); `extract_list_old.csv` is a previous case's list kept for reference. Values are `.strip()`ped, so the whitespace after commas in the CSV is intentional-tolerant, not meaningful.
- **`rotate_pdf.py` parses list arguments with `eval()`** and its angle-per-page index arithmetic for `even`/`odd`/`all` is easy to get off by one — check it when touching that branch.

## Data handling

The PDFs processed here are real case files containing personal medical data. `.gitignore` excludes `*.pdf` (and the WSL `*:Zone.Identifier` sidecar files) for that reason — do not commit case documents or add exceptions to that rule. Note that `extract_list.csv` and `extract_list_old.csv` *are* tracked and their output filenames carry case details.
