"""Tests für die Signal-Frische. Deterministisch (fixes heute), kein Netz.

Standalone:  PYTHONUTF8=1 PYTHONPATH=. python product/bridge/test_signal_freshness.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from product.bridge import signal_freshness as fr  # noqa: E402

HEUTE = date(2026, 6, 21)


# ─── relative Angaben ────────────────────────────────────────────────────────

def test_relativ_deutsch():
    assert fr.parse_relativ("Veröffentlicht vor 3 Tagen") == 3
    assert fr.parse_relativ("vor 2 Wochen aktualisiert") == 14
    assert fr.parse_relativ("vor 1 Monat") == 30
    assert fr.parse_relativ("vor 2 Monaten") == 60


def test_relativ_englisch():
    assert fr.parse_relativ("Posted 5 days ago") == 5
    assert fr.parse_relativ("3 weeks ago") == 21
    assert fr.parse_relativ("2 months ago") == 60


def test_relativ_heute_gestern():
    assert fr.parse_relativ("heute veröffentlicht") == 0
    assert fr.parse_relativ("Posted today") == 0
    assert fr.parse_relativ("gestern") == 1
    assert fr.parse_relativ("yesterday") == 1
    assert fr.parse_relativ("vorgestern") == 2


def test_relativ_stunden_minuten_ist_heute():
    assert fr.parse_relativ("vor 5 Stunden") == 0
    assert fr.parse_relativ("12 hours ago") == 0


def test_relativ_keine_angabe():
    assert fr.parse_relativ("") is None
    assert fr.parse_relativ("Vertriebsmitarbeiter im Außendienst gesucht") is None


# ─── absolute Daten ──────────────────────────────────────────────────────────

def test_absolut_iso():
    assert fr.parse_absolut("Datum: 2026-03-12") == date(2026, 3, 12)


def test_absolut_deutsch_punkt():
    assert fr.parse_absolut("veröffentlicht am 12.03.2026") == date(2026, 3, 12)


def test_absolut_deutscher_monatsname():
    assert fr.parse_absolut("Stand 12. März 2026") == date(2026, 3, 12)


def test_absolut_englischer_monatsname():
    assert fr.parse_absolut("Mar 12, 2026") == date(2026, 3, 12)
    assert fr.parse_absolut("April 5, 2026") == date(2026, 4, 5)


def test_absolut_keins():
    assert fr.parse_absolut("PLZ 10117 Berlin") is None


# ─── signal_alter_tage: kombiniert ───────────────────────────────────────────

def test_alter_relativ_schlaegt_absolut():
    assert fr.signal_alter_tage("vor 3 Tagen", heute=HEUTE) == 3


def test_alter_aus_absolutem_datum():
    # 12.03.2026 → 101 Tage vor dem 21.06.2026
    assert fr.signal_alter_tage("veröffentlicht 12.03.2026", heute=HEUTE) == 101


def test_alter_weite_zukunft_ist_unbekannt():
    # Datum weit in der Zukunft = vermutlich Fehlparse → ehrlich None (nicht „heute").
    assert fr.signal_alter_tage("2026-12-31", heute=HEUTE) is None


def test_alter_minimale_zukunft_geklemmt():
    # Bis 2 Tage Zukunft = Uhr-/Zeitzonen-Versatz → auf 0 geklemmt.
    assert fr.signal_alter_tage("2026-06-22", heute=HEUTE) == 0


def test_alter_unbekannt():
    assert fr.signal_alter_tage("kein datum hier", heute=HEUTE) is None


# ─── Label + Faktor ──────────────────────────────────────────────────────────

def test_frische_text():
    assert fr.frische_text(0) == "heute"
    assert fr.frische_text(1) == "gestern"
    assert fr.frische_text(3) == "vor 3 Tagen"
    assert fr.frische_text(10) == "vor 1 Woche"
    assert fr.frische_text(21) == "vor 3 Wochen"
    assert fr.frische_text(45) == "vor 1 Monat"
    assert fr.frische_text(120) == "vor 4 Monaten"
    assert fr.frische_text(400) == "über 1 Jahr"
    assert fr.frische_text(None) == ""


def test_frische_faktor_staffelung():
    assert fr.frische_faktor(None) == 1.0   # unbekannt → kein Abschlag
    assert fr.frische_faktor(3) == 1.0
    assert fr.frische_faktor(14) == 1.0
    assert fr.frische_faktor(25) == 0.92
    assert fr.frische_faktor(45) == 0.80
    assert fr.frische_faktor(80) == 0.65
    assert fr.frische_faktor(200) == 0.50


def test_ist_veraltet():
    assert fr.ist_veraltet(120) is True
    assert fr.ist_veraltet(30) is False
    assert fr.ist_veraltet(None) is False


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {fn.__name__}: {exc}")
    print(f"== {ok}/{len(fns)} grün ==")
    return ok == len(fns)


if __name__ == "__main__":
    sys.exit(0 if _run_all() else 1)
