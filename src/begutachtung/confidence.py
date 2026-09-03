"""Wie sicher ist eine Seite, und muss sie eskaliert werden?

Der Lexikontreffer ist hier der wertvollste Einzelindikator: Tesseract meldet auf
zerfallenem Text oft hohe Konfidenz fuer Zeichenfolgen, die kein Wort sind.
Ein Woerterbuchabgleich entlarvt genau diesen Fall und kostet nichts.

Die Schwellen sind Startwerte. Sie werden in Phase 7 gegen den Referenzsatz
kalibriert - bis dahin sind es begruendete Vermutungen, keine Messwerte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path

from .engines.base import PageResult

WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüß]{4,}")

# Zahlen, Dosierungen und Daten. Bei Uneinigkeit werden solche Spannen nie
# automatisch aufgeloest - ein Modell waehlt die plausible Dosis, nicht die
# geschriebene.
NUMERIC_RE = re.compile(
    r"\d|\b(?:mg|ml|mmol|g/dl|IE|µg|mcg|mmHg|kg|cm|mval)\b", re.IGNORECASE
)


class PageClass(str, Enum):
    DRUCK = "druck"
    DEGRADIERT = "degradiert"
    FORMULAR = "formular"
    HANDSCHRIFT = "handschrift"
    TABELLE = "tabelle"
    BILD = "bild"
    LEER = "leer"


@dataclass
class Thresholds:
    """Schwellen fuer das Eskalations-Gate.

    Kalibriert an 20 echten Aktenseiten aus zwei Faellen (400 dpi, tessdata_best,
    deu+eng). Gemessene Trennung: unauffaellige Seiten liegen bei 83-94 %
    Lexikontreffer, erkennbar kaputte bei 4-70 %. Dazwischen ist Platz.

    Die beiden Signale ergaenzen sich nachweislich statt sich zu doppeln: eine
    Seite der Stichprobe hatte Wortkonfidenz 0,89 - also scheinbar sauber - bei
    nur 70 % Lexikontreffer. Tesseract war sich sicher und produzierte trotzdem
    keine Woerter. Ueber die Konfidenz allein waere sie durchgerutscht.
    """

    min_word_conf: float = 0.75
    min_lexicon_rate: float = 0.78
    always_escalate: frozenset[PageClass] = field(
        default_factory=lambda: frozenset({PageClass.FORMULAR, PageClass.HANDSCHRIFT})
    )
    never_escalate: frozenset[PageClass] = field(
        default_factory=lambda: frozenset({PageClass.BILD, PageClass.LEER})
    )
    # Kurzschluss: sauberer Druck mit hoher Konfidenz und plausiblem Wortschatz
    # ueberspringt alles Weitere - auch im teuersten Preset. Das ist der Grund,
    # warum "best" auf einer ueberwiegend sauberen Akte nicht das Vierfache kostet.
    shortcut_conf: float = 0.88
    shortcut_lexicon: float = 0.88
    # 0.88 statt 0.95: gemessen erreichen auch einwandfreie Seiten hoechstens
    # 94 % Lexikontreffer, weil deutsche Komposita und Eigennamen immer eine
    # Restluecke lassen. Bei 0.95 haette der Kurzschluss praktisch nie gegriffen
    # und das Preset "best" haette jede Seite bezahlt.


@dataclass
class PageAssessment:
    page: int
    page_class: PageClass
    mean_conf: float | None
    lexicon_rate: float | None
    word_count: int
    escalate: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def reason_text(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "unauffällig"


@lru_cache(maxsize=4)
def load_lexicon(path: str | None) -> frozenset[str]:
    """Woerterliste laden. Ohne Liste liefert die Rate None statt zu raten."""
    if not path:
        return frozenset()
    p = Path(path)
    if not p.exists():
        return frozenset()
    return frozenset(
        w.strip().lower() for w in p.read_text(encoding="utf-8", errors="replace").splitlines()
        if w.strip()
    )


MIN_PART = 4
MAX_PARTS = 3
# Fugenelemente: "Berufsgenossenschaft" = Berufs + genossenschaft,
# "Rentenversicherung" = Renten + versicherung.
LINKERS = ("", "s", "n", "en", "es")
# Kurze Vorsilben, die unter MIN_PART liegen, aber sehr haeufig Komposita
# anfuehren - ohne sie faellt "Vorerkrankungen" durch.
PREFIXES = (
    "vor", "nach", "un", "ab", "an", "auf", "aus", "bei", "ein", "mit", "zu",
    "über", "unter", "ent", "er", "ver", "zer", "be", "ge", "wieder", "neben",
)


def is_compound(word: str, lexicon: frozenset[str], depth: int = MAX_PARTS) -> bool:
    """Ob sich ein Wort in bekannte Bestandteile zerlegen laesst.

    Ohne das ist der Indikator auf deutschen Fachtexten unbrauchbar: gemessen an
    echten Aktenseiten sind die haeufigsten Nicht-Treffer keine OCR-Fehler,
    sondern korrekte Komposita - Berufsgenossenschaft, Unfallversicherungstraeger,
    Vorerkrankungen. Die als Muell zu zaehlen wuerde die halbe Akte grundlos
    eskalieren.
    """
    if word in lexicon:
        return True
    if depth <= 1:
        return False

    # Vorsilbe abtrennen und den Rest pruefen ("vor|erkrankungen").
    for prefix in PREFIXES:
        if word.startswith(prefix) and len(rest := word[len(prefix):]) >= MIN_PART:
            if rest in lexicon or is_compound(rest, lexicon, depth - 1):
                return True

    if len(word) < 2 * MIN_PART:
        return False
    for cut in range(MIN_PART, len(word) - MIN_PART + 1):
        head, tail = word[:cut], word[cut:]
        if head not in lexicon:
            continue
        for linker in LINKERS:
            if tail.startswith(linker) and len(rest := tail[len(linker):]) >= MIN_PART:
                if is_compound(rest, lexicon, depth - 1):
                    return True
    return False


def lexicon_rate(text: str, lexicon: frozenset[str]) -> float | None:
    """Anteil der laengeren Woerter, die als deutsche Woerter durchgehen.

    Nur Tokens ab vier Buchstaben, weil kurze Fragmente auch bei sauberer
    Erkennung haeufig keine Woerter sind (Abkuerzungen, Masseinheiten).
    """
    if not lexicon:
        return None
    tokens = WORD_RE.findall(text)
    if not tokens:
        return None
    hits = sum(1 for t in tokens if is_compound(t.lower(), lexicon))
    return hits / len(tokens)


def has_numeric_content(text: str) -> bool:
    """Ob eine Spanne unter die Zahlen-Sperre faellt."""
    return bool(NUMERIC_RE.search(text))


def assess(
    result: PageResult,
    page_class: PageClass,
    thresholds: Thresholds | None = None,
    lexicon: frozenset[str] = frozenset(),
    ink_coverage: float | None = None,
) -> PageAssessment:
    """Entscheidet, ob eine Seite teure Rechenzeit bekommt."""
    th = thresholds or Thresholds()
    conf = result.mean_conf
    rate = lexicon_rate(result.text, lexicon)
    words = result.word_count
    reasons: list[str] = []

    if page_class in th.never_escalate:
        return PageAssessment(result.page, page_class, conf, rate, words, False,
                              [f"Klasse {page_class.value} - keine OCR noetig"])

    if page_class in th.always_escalate:
        reasons.append(f"Klasse {page_class.value}")

    if conf is not None and conf < th.min_word_conf:
        reasons.append(f"Wortkonfidenz {conf:.2f}")

    if rate is not None and rate < th.min_lexicon_rate:
        reasons.append(f"Lexikontreffer {rate:.0%}")

    # Etwas steht auf der Seite, aber niemand hat es gelesen.
    if ink_coverage is not None and ink_coverage > 0.01 and words < 20:
        reasons.append(f"Tinte {ink_coverage:.1%}, aber nur {words} Wörter")

    # Der Kurzschluss darf nur greifen, wenn ueberhaupt kein Verdacht besteht.
    # Er soll weitere Arbeit an unauffaelligen Seiten sparen, nicht einen bereits
    # erkannten Befund ueberstimmen - eine Seite mit viel Tinte und einem einzigen
    # sicher erkannten Wort ist nicht "sauberer Druck", auch wenn die Konfidenz
    # dieses einen Wortes hoch ist.
    if not reasons and page_class == PageClass.DRUCK:
        confident = conf is not None and conf > th.shortcut_conf
        plausible = rate is None or rate > th.shortcut_lexicon
        if confident and plausible:
            return PageAssessment(result.page, page_class, conf, rate, words, False,
                                  ["sauberer Druck, hohe Konfidenz"])

    return PageAssessment(result.page, page_class, conf, rate, words, bool(reasons), reasons)
