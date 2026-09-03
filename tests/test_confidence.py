"""Eskalations-Gate und Zahlen-Sperre."""

import pytest

from begutachtung.confidence import (
    PageClass,
    Thresholds,
    assess,
    has_numeric_content,
    lexicon_rate,
)
from begutachtung.engines.base import Line, PageResult, Word

LEX = frozenset({"diagnose", "befund", "verlauf", "beurteilung", "patient", "therapie"})


def page(texts_and_confs, page_no=1):
    lines = []
    for text, conf in texts_and_confs:
        words = [Word(text=w, conf=conf) for w in text.split()]
        line = Line(text=text, words=words, conf=conf)
        lines.append(line)
    return PageResult(engine="tesseract", page=page_no, lines=lines)


class TestLexicon:
    def test_rate_counts_only_long_tokens(self):
        # "mg" und "5" sind zu kurz bzw. keine Buchstaben - zaehlen nicht mit
        assert lexicon_rate("Diagnose Befund 5 mg", LEX) == 1.0

    def test_garbage_scores_low(self):
        assert lexicon_rate("Diagnnse Befnnd Verlanf", LEX) == 0.0

    def test_without_lexicon_returns_none(self):
        """Ohne Woerterliste wird nicht geraten."""
        assert lexicon_rate("Diagnose", frozenset()) is None

    def test_no_usable_tokens_returns_none(self):
        assert lexicon_rate("5 mg 130/85", LEX) is None


class TestNumericLock:
    @pytest.mark.parametrize("text", [
        "Prednisolon 5 mg", "Blutdruck 130/85", "vom 14.03.2024",
        "20 ml", "3,5 mmol", "120 mmHg", "1000 IE",
    ])
    def test_numeric_spans_are_detected(self, text):
        assert has_numeric_content(text)

    @pytest.mark.parametrize("text", [
        "Beurteilung folgt", "Der Patient berichtet", "unauffälliger Befund",
    ])
    def test_plain_prose_is_not(self, text):
        assert not has_numeric_content(text)


class TestEscalation:
    def test_clean_print_short_circuits(self):
        r = page([("Diagnose Befund Verlauf", 0.95)])
        a = assess(r, PageClass.DRUCK, lexicon=LEX)
        assert not a.escalate

    def test_low_confidence_escalates(self):
        r = page([("Diagnose Befund Verlauf", 0.55)])
        a = assess(r, PageClass.DRUCK, lexicon=LEX)
        assert a.escalate
        assert "Wortkonfidenz" in a.reason_text

    def test_garbage_text_escalates_despite_high_confidence(self):
        """Der Fall, den die Konfidenz allein nicht faengt: Tesseract ist sich
        sicher, produziert aber keine Woerter."""
        r = page([("Diagnnse Befnnd Verlanf Bexrteilung", 0.93)])
        a = assess(r, PageClass.DRUCK, lexicon=LEX)
        assert a.escalate
        assert "Lexikontreffer" in a.reason_text

    def test_form_always_escalates_even_when_confident(self):
        """Auf einem Formular ist Tesseract fuer die handschriftlichen
        Eintragungen blind - egal wie zufrieden es mit dem Vordruck ist."""
        r = page([("Diagnose Befund Verlauf", 0.97)])
        a = assess(r, PageClass.FORMULAR, lexicon=LEX)
        assert a.escalate

    def test_handwriting_always_escalates(self):
        r = page([("Diagnose", 0.99)])
        assert assess(r, PageClass.HANDSCHRIFT, lexicon=LEX).escalate

    def test_blank_and_image_pages_never_escalate(self):
        r = page([])
        for cls in (PageClass.LEER, PageClass.BILD):
            assert not assess(r, cls, lexicon=LEX).escalate

    def test_ink_without_words_escalates(self):
        r = page([("x", 0.9)])
        a = assess(r, PageClass.DRUCK, lexicon=LEX, ink_coverage=0.05)
        assert a.escalate
        assert "Tinte" in a.reason_text

    def test_thresholds_are_configurable(self):
        r = page([("Diagnose Befund Verlauf", 0.80)])
        assert not assess(r, PageClass.DRUCK, lexicon=LEX).escalate
        strict = Thresholds(min_word_conf=0.90)
        assert assess(r, PageClass.DRUCK, strict, lexicon=LEX).escalate


class TestPageResult:
    def test_mean_conf_is_length_weighted(self):
        r = page([("a" * 100, 1.0), ("b", 0.0)])
        # Die lange sichere Zeile dominiert
        assert r.mean_conf > 0.95

    def test_mean_conf_none_without_data(self):
        assert PageResult(engine="x", page=1).mean_conf is None


class TestCompounds:
    """Deutsche Komposita muessen als Woerter durchgehen.

    Gemessen an echten Aktenseiten waren die haeufigsten Nicht-Treffer keine
    OCR-Fehler, sondern korrekte Wortzusammensetzungen. Ohne Zerlegung lag die
    Trefferquote bei 80 % und haette die halbe Akte grundlos eskaliert; mit
    Zerlegung bei 91 %.
    """

    LEX = frozenset({
        "beruf", "berufs", "genossenschaft", "gesundheit", "gesundheits",
        "dienst", "erkrankungen", "krankheit", "krankheits", "bericht",
        "diagnose", "befund", "renten", "versicherung", "nummer",
    })

    @pytest.mark.parametrize("word", [
        "berufsgenossenschaft",      # Fugen-s
        "gesundheitsdienst",
        "krankheitsbericht",
        "rentenversicherung",
        "rentenversicherungsnummer",  # drei Teile
        "vorerkrankungen",            # kurze Vorsilbe unter der Mindestlaenge
    ])
    def test_real_compounds_count_as_words(self, word):
        from begutachtung.confidence import is_compound
        assert is_compound(word, self.LEX)

    @pytest.mark.parametrize("word", [
        "diagnnse", "befnnd", "xyzabc", "qqqqwwww",
    ])
    def test_ocr_garbage_still_rejected(self, word):
        from begutachtung.confidence import is_compound
        assert not is_compound(word, self.LEX)

    def test_decomposition_terminates_on_long_garbage(self):
        """Rekursion darf bei langem Muell nicht explodieren."""
        from begutachtung.confidence import is_compound
        assert not is_compound("x" * 200, self.LEX)
