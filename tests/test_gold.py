"""Der Referenzsatz, der beim Prüfen entsteht."""

import json

from begutachtung.gold import Correction, add, count, load


def test_add_and_load(tmp_path):
    add("abc123", Correction(page=7, line=2, ocr="Diagnnse", gold="Diagnose"), root=tmp_path)
    got = load("abc123", root=tmp_path)
    assert list(got) == [(7, 2)]
    assert got[(7, 2)].gold == "Diagnose"
    assert got[(7, 2)].ts > 0


def test_newest_correction_wins(tmp_path):
    """Zweimal dieselbe Zeile korrigiert ergibt einen Eintrag, nicht zwei -
    die Historie bleibt in der Datei, die Auswertung sieht nur die jüngste."""
    add("abc123", Correction(page=1, line=0, ocr="x", gold="erster"), root=tmp_path)
    add("abc123", Correction(page=1, line=0, ocr="x", gold="zweiter"), root=tmp_path)
    got = load("abc123", root=tmp_path)
    assert len(got) == 1
    assert got[(1, 0)].gold == "zweiter"
    # beide Zeilen stehen weiterhin in der Datei
    raw = (tmp_path / "abc123" / "lines.jsonl").read_text(encoding="utf-8")
    assert len(raw.strip().splitlines()) == 2


def test_pages_and_lines_are_separate_keys(tmp_path):
    for page in (1, 2):
        for line in (0, 1):
            add("d", Correction(page=page, line=line, ocr="o", gold=f"{page}-{line}"),
                root=tmp_path)
    assert count("d", root=tmp_path) == 4


def test_unchanged_marks_confirmation(tmp_path):
    """Eine bestätigte Zeile ist auch ein Datenpunkt: sie belegt, dass die
    Erkennung hier richtig lag."""
    c = Correction(page=1, line=0, ocr="Befund ", gold="Befund")
    assert c.unchanged
    assert not Correction(page=1, line=0, ocr="Befnnd", gold="Befund").unchanged


def test_truncated_last_line_is_skipped(tmp_path):
    """Nach einem Absturz kann die letzte Zeile halb geschrieben sein."""
    add("d", Correction(page=1, line=0, ocr="o", gold="gut"), root=tmp_path)
    with open(tmp_path / "d" / "lines.jsonl", "a", encoding="utf-8") as fh:
        fh.write('{"page": 2, "line": 0, "ocr": "x", "go')
    got = load("d", root=tmp_path)
    assert len(got) == 1 and got[(1, 0)].gold == "gut"


def test_unknown_fields_are_ignored(tmp_path):
    path = tmp_path / "d"
    path.mkdir()
    (path / "lines.jsonl").write_text(json.dumps({
        "page": 1, "line": 0, "ocr": "o", "gold": "g", "aus_der_zukunft": True,
    }) + "\n", encoding="utf-8")
    assert load("d", root=tmp_path)[(1, 0)].gold == "g"


def test_missing_file_is_empty_not_an_error(tmp_path):
    assert load("gibtsnicht", root=tmp_path) == {}
    assert count("gibtsnicht", root=tmp_path) == 0


def test_bbox_survives_the_round_trip(tmp_path):
    """Ohne bbox lässt sich der Bildausschnitt später nicht reproduzieren -
    und damit wäre der Datenpunkt für die Messung wertlos."""
    add("d", Correction(page=3, line=1, ocr="o", gold="g", bbox=[10, 20, 300, 40],
                        conf=0.42), root=tmp_path)
    c = load("d", root=tmp_path)[(3, 1)]
    assert c.bbox == [10, 20, 300, 40]
    assert c.conf == 0.42
