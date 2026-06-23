"""Tests für die Premium-Gate-Ausgabepolitik in engine_bridge (Schritt 4).

Testet die reinen, netzfreien Helfer `_uebersuch_roh_ziel` (Über-Suchen) und
`_gate_ausgabe` (REJECT raus, PREMIUM zuerst, Zielmenge der besten) — ohne die
Engine/den Subprozess zu starten.
"""
from __future__ import annotations

from product.bridge import engine_bridge as eb
from product.bridge import premium_gate as pg


def _premium(**over) -> dict:
    """Ein Lead, der das Premium-Gate als PREMIUM passiert (Zielbranche Maschinenbau)."""
    lead = {
        "entdeckt_per_signal": "sales_hiring",
        "signal_quelle_url": "https://stepstone.de/job/1",
        "website": "https://www.echte-firma.de",
        "company_name": "Echte Maschinenbau GmbH",
        "contact_full_name": "Anna Beispiel",
        "email": "anna.beispiel@echte-firma.de",
        "phone": "+49 151 23456789",
        "ready_to_send": "yes",
        "email_quality_rank": "A",
        "signal_alter_tage": 7,
        "industry": "Maschinenbau",
        "kaufbereitschaft_score": 80,
    }
    lead.update(over)
    return lead


# ── Über-Suchen ─────────────────────────────────────────────────────────────
def test_uebersuch_default_dreifach(monkeypatch):
    monkeypatch.delenv("SIGNAL_UEBERSUCH_FAKTOR", raising=False)
    monkeypatch.delenv("SIGNAL_UEBERSUCH_MAX", raising=False)
    assert eb._uebersuch_roh_ziel(10) == 30
    assert eb._uebersuch_roh_ziel(50) == 80          # 150 auf Cap 80 gedeckelt


def test_uebersuch_faktor_aus(monkeypatch):
    monkeypatch.setenv("SIGNAL_UEBERSUCH_FAKTOR", "1")
    assert eb._uebersuch_roh_ziel(10) == 10          # Faktor 1 = altes Verhalten


def test_uebersuch_env_steuerbar(monkeypatch):
    monkeypatch.setenv("SIGNAL_UEBERSUCH_FAKTOR", "2")
    monkeypatch.setenv("SIGNAL_UEBERSUCH_MAX", "100")
    assert eb._uebersuch_roh_ziel(20) == 40


def test_uebersuch_defensiv_bei_muell(monkeypatch):
    monkeypatch.setenv("SIGNAL_UEBERSUCH_FAKTOR", "abc")
    assert eb._uebersuch_roh_ziel(10) == 30          # fällt auf Default 3 zurück


# ── Gate-Ausgabe ────────────────────────────────────────────────────────────
def test_gate_ausgabe_wirft_reject_raus():
    leads = [_premium(), _premium(website="")]       # 2. = keine echte Website = REJECT
    aus, z = eb._gate_ausgabe(leads, ziel=10, zielbranche="Maschinenbau")
    assert z[pg.PREMIUM] == 1 and z[pg.REJECT] == 1
    assert len(aus) == 1
    assert all(l.get("premium_klasse") != pg.REJECT for l in aus)


def test_gate_ausgabe_premium_zuerst():
    leads = [
        _premium(ready_to_send="no", company_name="Review GmbH"),   # → REVIEW
        _premium(company_name="Premium GmbH"),                      # → PREMIUM
    ]
    aus, _ = eb._gate_ausgabe(leads, ziel=10, zielbranche="Maschinenbau")
    assert aus[0]["company_name"] == "Premium GmbH"
    assert aus[0]["premium_klasse"] == pg.PREMIUM


def test_gate_ausgabe_nur_premium():
    leads = [_premium(ready_to_send="no"), _premium()]
    aus, _ = eb._gate_ausgabe(leads, ziel=10, zielbranche="Maschinenbau", nur_premium=True)
    assert len(aus) == 1 and aus[0]["premium_klasse"] == pg.PREMIUM


def test_gate_ausgabe_cap_haelt_alle_premium():
    # Zielmenge < Premium-Zahl → ALLE Premium kommen trotzdem durch (nie kappen unter Premium).
    leads = [_premium(company_name=f"Maschinenbau {i} GmbH") for i in range(5)]
    aus, z = eb._gate_ausgabe(leads, ziel=2, zielbranche="Maschinenbau")
    assert z[pg.PREMIUM] == 5
    assert len(aus) == 5


def test_gate_ausgabe_liefert_zielmenge_der_besten():
    # 1 Premium + 4 Review, ziel=3 → Premium + 2 beste Review (nach Score) = 3.
    leads = [_premium()] + [
        _premium(ready_to_send="no", company_name=f"Review {i} GmbH",
                 kaufbereitschaft_score=50 - i)
        for i in range(4)
    ]
    aus, _ = eb._gate_ausgabe(leads, ziel=3, zielbranche="Maschinenbau")
    assert len(aus) == 3
    assert aus[0]["premium_klasse"] == pg.PREMIUM
    # die zwei besten Review (Score 50, 49) vor den schwächeren (48, 47).
    assert aus[1]["kaufbereitschaft_score"] == 50
    assert aus[2]["kaufbereitschaft_score"] == 49


def test_gate_ausgabe_taggt_jeden_lead():
    leads = [_premium(), _premium(ready_to_send="no"), _premium(website="")]
    eb._gate_ausgabe(leads, ziel=10, zielbranche="Maschinenbau")
    for l in leads:
        assert l.get("premium_klasse") in (pg.PREMIUM, pg.REVIEW, pg.REJECT)
