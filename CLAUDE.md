# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Tooling for preparing scanned medical/legal case files ("Begutachtung") for expert review. The
workflow is a manual pipeline over PDFs, not an application:

1. **OCR** a scanned case file (`Akte.pdf`) — `ocr_batch.sh`, using `ocrmypdf` in Docker.
2. **Rotate** pages the scanner fed upside down — `rotate_pdf.py`.
3. **Extract** the relevant page ranges into individually named documents — `extractor.py`,
   driven by a CSV list.

Each step is run by hand. There is no build and no test suite yet.

## Working corpus

The real case files are **not** in this repo. They live at
`/mnt/c/Users/carst/Downloads/Gutachten_Eichelberger` — 40 case folders, ~1.3 GB, each with
`Akte.pdf` (or `Akte01/02.pdf`), `Anschreiben.pdf`, `info.txt` and versioned `Gutachten_*.docx`.

A typical `Akte.pdf` is **120–260 pages of pure scan with no text layer**. Assume this shape when
reasoning about runtime and cost. These are real patient records — never commit them, never write
their contents into the repo, and prefer aggregate metrics over dumping recognized text.

## Setup

```bash
make check       # what's missing
make image       # docker pull jbarlow83/ocrmypdf
make tessdata    # download tessdata_best deu+eng into docker/tessdata/ (~23 MB, gitignored)

conda env create -f environment.yml && conda activate ocr_env
```

OCR runs entirely in Docker; the conda env only covers host-side PDF manipulation (`pypdf`,
`pymupdf`). There is **no local tesseract or ocrmypdf** in WSL — every OCR call goes through the
container.

## Commands

```bash
./ocr_batch.sh                      # OCR every PDF in the current directory
./ocr_batch.sh ~/Akten/Fall_Mueller
./ocr_batch.sh . --oversample 600   # extra args are passed through to ocrmypdf

python rotate_pdf.py Akte.pdf              # default: even pages, 180°
python rotate_pdf.py Akte.pdf odd 270
python rotate_pdf.py Akte.pdf "[2,4,6]" "[90,180,270]"

python extractor.py                 # splits the ranges listed in extract_list.csv

# Page-level analysis (the `begutachtung` package; needs `pip install -e .`)
begutachtung inspect Akte.pdf
begutachtung analyze Akte.pdf --lexicon config/lexicon/base.txt --pages 40-80
begutachtung purge Akte.pdf         # drops the page-image cache for that file
```

There is **no dashboard yet** — `begutachtung ui` does not exist. It is Phase 4 of the plan; do
not document or reference it as though it works.

Env overrides for `ocr_batch.sh`: `OCR_JOBS` (default 8), `OCR_LANGS` (default `deu+eng`),
`OCR_OVERSAMPLE` (default 400).

## Things to know before changing this

- **`--redo-ocr` and `--deskew` are mutually exclusive** in ocrmypdf — combining them aborts with a
  pydantic validation error. `ocr_batch.sh` therefore picks a mode per file: files that already
  carry a text layer get `--redo-ocr` (preserves crisp digital text), pure scans get `--force-ocr`
  plus the full image preprocessing. Detection lives in `docker/detect_text.py` and runs *inside*
  the container, because the host has no Python with a PDF text extractor.
- **Do not set `TESSDATA_PREFIX` to a directory holding only `.traineddata` files.** It replaces
  the image's tessdata directory wholesale, which loses `configs/` (`hocr`, `txt`, `tsv`) and makes
  ocrmypdf fail with `Can't open hocr`. `ocr_batch.sh` instead bind-mounts the individual language
  files over the image's own, discovering the path from `tesseract --list-langs`.
- **`--clean` is safe, `--clean-final` and `--remove-background` are not.** On faxed medical forms
  the latter two delete table rules and faint handwriting.
- **`--jobs 8`, not 32.** RAM (15 GB) is the binding constraint, not the 32 cores.
- **`extractor.py` reads `extract_list.csv` from the current working directory** — the filename is
  hardcoded, not an argument. `extract_list_example.csv` documents the format
  (`page_range,input_pdf,output_pdf`, 1-based inclusive); `extract_list_old.csv` is a previous
  case's list kept for reference.
- Any change to `ocr_batch.sh` output must keep the `OCR_<name>.pdf` **prefix** convention and the
  page count identical, or `extractor.py`'s page ranges break.

## The package (`src/begutachtung/`)

Stage 1 of the planned cascade: rasterize (PyMuPDF) → Tesseract via Docker → classify → assess.
Points worth knowing before changing it:

- **Tesseract is driven with TSV output, not hOCR or `--sidecar`.** TSV gives word boxes *and* word
  confidences with far less parsing. Lines are keyed by `(block_num, par_num, line_num)` — `line_num`
  alone repeats across paragraphs, so grouping by it merges unrelated lines.
- **`EngineInfo.is_local` is the only place the local/cloud distinction is encoded.** The approval
  gate and audit log will key off it. Never write `if engine == "claude"` anywhere.
- **`EngineInfo.provides_geometry` is true only for Tesseract.** Vision models produce good text but
  unreliable coordinates; reconciliation must use a geometry-providing engine as the skeleton so
  invented boxes can never reach the PDF text layer.
- **The lexicon is generated, not vendored.** `make lexicon` converts the DAWG inside
  `tessdata_best` back into a word list (237k entries). German compounds are decomposed — without
  that the hit rate sits at 80 % and flags correct words like *Berufsgenossenschaft* as garbage.
- The cache lives at `~/.cache/begutachtung/<sha256[:12]>/` and holds page images from patient
  records. Writes are `.tmp` + `os.replace()` so an interrupted run leaves no half file.

## Measured baselines

Numbers from 20 real pages sampled across two case files, comparing the old configuration
(150 dpi, `tessdata_fast`, `-l deu`) with the current one (400 dpi, `tessdata_best`, `-l deu+eng`):

| | old | current |
|---|---|---|
| Mean Tesseract word confidence | 75.3 % | **79.2 %** |
| Words recognized | 3663 | **3908** (+6.7 %) |

Better on 15 of 20 pages, worse on 2. Gains concentrate on the degraded pages (worst page:
45.8 % → 60.2 %). Note this is Tesseract's *self-reported* confidence, not ground truth — a real
CER measurement needs a gold set (planned, see below). One sampled page yields zero words in both
configurations; such pages are radiology images or blanks and should eventually be classified and
skipped rather than OCR'd.

Handwriting is **not** addressed by any of this. Tesseract scores ~45 % on handwriting; filled-in
forms and checkboxes need a vision model.

## Where this is going

The approved plan (`~/.claude/plans/ich-moechte-das-ocr-twinkling-rocket.md`) restructures this
into a page-level adaptive cascade: Tesseract on every page, Claude vision only on pages Tesseract
flags as uncertain, LLM adjudication only on disagreeing lines — with `--budget fast|balanced|best`
and a cost cap. Two rules from that plan matter for any change made in the meantime:

- **Never let a vision model be the sole source of a number.** Any span with digits, a dose/unit
  pattern or a date where engines disagree gets flagged for human review, never auto-resolved.
- **Never add a "send the whole page transcript to an LLM to clean up" pass.** It fabricates
  plausible German medical prose, which is the worst possible failure mode here.
