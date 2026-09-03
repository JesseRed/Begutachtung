"""Das TSV-Parsing ohne Docker pruefen."""

from begutachtung.engines.base import BBox
from begutachtung.engines.tesseract import parse_tsv

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def row(level, block, par, line, word, left, top, w, h, conf, text=""):
    return f"{level}\t1\t{block}\t{par}\t{line}\t{word}\t{left}\t{top}\t{w}\t{h}\t{conf}\t{text}"


def test_words_are_grouped_into_lines():
    tsv = "\n".join([
        HEADER,
        row(4, 1, 1, 1, 0, 10, 20, 300, 30, -1),
        row(5, 1, 1, 1, 1, 10, 20, 100, 30, 96, "Diagnose:"),
        row(5, 1, 1, 1, 2, 120, 20, 180, 30, 88, "Post-COVID"),
        row(4, 1, 1, 2, 0, 10, 60, 250, 30, -1),
        row(5, 1, 1, 2, 1, 10, 60, 250, 30, 72, "Verlauf"),
    ])
    lines = parse_tsv(tsv)

    assert len(lines) == 2
    assert lines[0].text == "Diagnose: Post-COVID"
    assert lines[0].bbox == BBox(10, 20, 300, 30)
    assert lines[0].conf == (0.96 + 0.88) / 2
    assert lines[1].text == "Verlauf"


def test_line_numbers_repeat_across_paragraphs():
    """line_num ist nur innerhalb eines Absatzes eindeutig - wer nur danach
    gruppiert, verschmilzt Zeilen aus verschiedenen Absaetzen."""
    tsv = "\n".join([
        HEADER,
        row(5, 1, 1, 1, 1, 0, 0, 50, 10, 90, "erster"),
        row(5, 1, 2, 1, 1, 0, 40, 50, 10, 90, "zweiter"),
        row(5, 2, 1, 1, 1, 0, 80, 50, 10, 90, "dritter"),
    ])
    lines = parse_tsv(tsv)
    assert [line.text for line in lines] == ["erster", "zweiter", "dritter"]


def test_empty_words_and_boxes_without_text_are_dropped():
    tsv = "\n".join([
        HEADER,
        row(4, 1, 1, 1, 0, 10, 20, 300, 30, -1),   # Zeilenbox ohne Woerter
        row(4, 1, 1, 2, 0, 10, 60, 300, 30, -1),
        row(5, 1, 1, 2, 1, 10, 60, 100, 30, 91, "Befund"),
        row(5, 1, 1, 2, 2, 0, 0, 0, 0, -1, "   "),  # leerer Text
    ])
    lines = parse_tsv(tsv)
    assert len(lines) == 1
    assert lines[0].text == "Befund"
    assert len(lines[0].words) == 1


def test_malformed_rows_do_not_crash():
    tsv = "\n".join([
        HEADER,
        "kaputt\tzeile",
        row(5, 1, 1, 1, 1, 0, 0, 10, 10, 80, "gut"),
    ])
    assert [line.text for line in parse_tsv(tsv)] == ["gut"]


def test_empty_input():
    assert parse_tsv("") == []
    assert parse_tsv(HEADER) == []
