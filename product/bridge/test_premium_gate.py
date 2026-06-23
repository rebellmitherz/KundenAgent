"""Tests fürs Premium-Gate — jede harte Regel bekommt ihren eigenen Lead.

Leitgedanke: ein PREMIUM-Lead muss ALLE Regeln erfüllen; das Kippen genau einer
Eigenschaft muss ihn aus PREMIUM herauswerfen (REVIEW oder REJECT). So ist
belegt, dass das Gate wirklich hart ist und nicht nur dekorativ.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from product.bridge import premium_gate as pg


def _premium_lead(**over) -> dict:
    """Ein Lead, der ALLE harten Regeln erfüllt → PREMIUM."""
    lead = {
        "entdeckt_per_signal": "sales_hiring",
        "signal_quelle_url": "https://www.stepstone.de/job/123",
        "website": "https://www.echte-firma.de",
        "company_name": "Echte Maschinenbau GmbH",
        "contact_full_name": "Anna Beispiel",
        "email": "anna.beispiel@echte-firma.de",
        "phone": "+49 151 23456789",
        "ready_to_send": "yes",
        "email_quality_rank": "A",
        "signal_alter_tage": 7,
        "industry": "Maschinenbau",
        "kaufbereitschaft_stufe": "hoch",
    }
    lead.update(over)
    return lead


def test_voller_lead_ist_premium():
    r = pg.bewerten_premium(_premium_lead(), zielbranche="Maschinenbau")
    assert r["klasse"] == pg.PREMIUM
    assert r["stufe_cap"] == pg.HOCH


# ── Regel 1: Signal + Beleg ─────────────────────────────────────────────────
def test_kein_signal_ist_reject():
    r = pg.bewerten_premium(_premium_lead(entdeckt_per_signal=""), zielbranche="Maschinenbau")
    assert r["klasse"] == pg.REJECT


def test_signal_ohne_beleg_ist_review():
    lead = _premium_lead(signal_quelle_url="", signal_belege=[])
    r = pg.bewerten_premium(lead, zielbranche="Maschinenbau")
    assert r["klasse"] == pg.REVIEW


def test_beleg_aus_signal_belege_liste_zaehlt():
    lead = _premium_lead(signal_quelle_url="",
                         signal_belege=[{"quelle_url": "https://x.de/job"}])
    r = pg.bewerten_premium(lead, zielbranche="Maschinenbau")
    assert r["klasse"] == pg.PREMIUM


# ── Regel 2: Frische ────────────────────────────────────────────────────────
def test_veralteter_beleg_ist_review():
    r = pg.bewerten_premium(_premium_lead(signal_alter_tage=200), zielbranche="Maschinenbau")
    assert r["klasse"] == pg.REVIEW


def test_unbekanntes_datum_bleibt_premium_aber_kein_hoch():
    r = pg.bewerten_premium(_premium_lead(signal_alter_tage=None), zielbranche="Maschinenbau")
    assert r["klasse"] == pg.PREMIUM
    assert r["stufe_cap"] == pg.MITTEL


# ── Regel 3: echte Website ──────────────────────────────────────────────────
@pytest.mark.parametrize("url", [
    "", "https://www.linkedin.com/company/x", "http://info.yourdomain.com",
    "https://example.com", "https://firmenname.de",
])
def test_fake_website_ist_reject(url):
    r = pg.bewerten_premium(_premium_lead(website=url), zielbranche="Maschinenbau")
    assert r["klasse"] == pg.REJECT


# ── Regel 4: Artefakt-Namen ─────────────────────────────────────────────────
def test_firma_artefakt_ist_reject():
    r = pg.bewerten_premium(_premium_lead(company_name="Amercia Inc"), zielbranche="Maschinenbau")
    assert r["klasse"] == pg.REJECT


def test_person_artefakt_blockt_premium():
    r = pg.bewerten_premium(_premium_lead(contact_full_name="Parmentier Dipl"),
                            zielbranche="Maschinenbau")
    assert r["klasse"] != pg.PREMIUM


# ── Regel 5: belastbarer Kontakt ────────────────────────────────────────────
def test_nur_rollen_mail_ohne_telefon_ist_review():
    lead = _premium_lead(email="info@echte-firma.de", phone="")
    r = pg.bewerten_premium(lead, zielbranche="Maschinenbau")
    assert r["klasse"] == pg.REVIEW


def test_rollen_mail_mit_telefon_bleibt_premium():
    lead = _premium_lead(email="info@echte-firma.de")  # Telefon bleibt gesetzt
    r = pg.bewerten_premium(lead, zielbranche="Maschinenbau")
    assert r["klasse"] == pg.PREMIUM


def test_gar_kein_kontakt_ist_reject():
    lead = _premium_lead(email="", phone="")
    r = pg.bewerten_premium(lead, zielbranche="Maschinenbau")
    assert r["klasse"] == pg.REJECT


# ── Regel 6: Engine-Urteil ──────────────────────────────────────────────────
def test_ready_to_send_no_ist_review():
    r = pg.bewerten_premium(_premium_lead(ready_to_send="no"), zielbranche="Maschinenbau")
    assert r["klasse"] == pg.REVIEW


def test_do_not_contact_ist_reject():
    r = pg.bewerten_premium(_premium_lead(do_not_contact=True), zielbranche="Maschinenbau")
    assert r["klasse"] == pg.REJECT


def test_fake_mail_rang_d_blockt_premium():
    r = pg.bewerten_premium(_premium_lead(email_quality_rank="D"), zielbranche="Maschinenbau")
    assert r["klasse"] != pg.PREMIUM


def test_invalid_email_block_ist_reject():
    lead = _premium_lead(ready_to_send_block_reason="invalid_or_risky_email")
    r = pg.bewerten_premium(lead, zielbranche="Maschinenbau")
    assert r["klasse"] == pg.REJECT


# ── Regel 7: ICP-Fit ────────────────────────────────────────────────────────
def test_rollenwort_als_zielbranche_ist_nicht_premium():
    # genau der Defekt: „Vertrieb" als Ziel matcht alles → ICP nicht prüfbar.
    r = pg.bewerten_premium(_premium_lead(industry="Vertrieb"), zielbranche="Vertrieb")
    assert r["klasse"] == pg.REVIEW


def test_falsche_branche_ist_reject():
    lead = _premium_lead(industry="Friseur", description="Friseursalon", company_name="Salon Schnitt")
    r = pg.bewerten_premium(lead, zielbranche="Maschinenbau")
    assert r["klasse"] == pg.REJECT


# ── Stufen-Deckelung (Kern-Fix gegen 33/39 = hoch) ──────────────────────────
def test_anreichern_deckelt_stufe_aber_hebt_nie_an():
    leads = [
        _premium_lead(kaufbereitschaft_stufe="hoch"),                 # PREMIUM → hoch bleibt
        _premium_lead(ready_to_send="no", kaufbereitschaft_stufe="hoch"),  # REVIEW → mittel
        _premium_lead(website="", kaufbereitschaft_stufe="hoch"),     # REJECT → niedrig
        _premium_lead(kaufbereitschaft_stufe="niedrig"),             # PREMIUM, aber niedrig bleibt niedrig
    ]
    zaehlung = pg.anreichern(leads, zielbranche="Maschinenbau")
    assert leads[0]["kaufbereitschaft_stufe"] == "hoch"
    assert leads[1]["kaufbereitschaft_stufe"] == "mittel"
    assert leads[2]["kaufbereitschaft_stufe"] == "niedrig"
    assert leads[3]["kaufbereitschaft_stufe"] == "niedrig"  # nie hochgestuft
    assert zaehlung[pg.PREMIUM] == 2
    assert zaehlung[pg.REVIEW] == 1
    assert zaehlung[pg.REJECT] == 1


def test_defekter_lead_kippt_nicht():
    r = pg.bewerten_premium({"website": 12345, "signal_belege": "kaputt"})
    assert r["klasse"] in (pg.REVIEW, pg.REJECT)  # nie stiller PREMIUM


# ── Smoke-Test am echten Lauf (falls vorhanden) ─────────────────────────────
def test_echter_lauf_smoke():
    pfad = Path("b2bbot/output/latest/signal_leads.json")
    if not pfad.exists():
        pytest.skip("kein echter Lauf vorhanden")
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    leads = daten.get("leads", [])
    zb = str(daten.get("zielgruppe") or "")
    zaehlung = pg.anreichern(leads, zielbranche=zb)
    # Summe stimmt und das Gate ist härter als das alte „33/39 = hoch".
    assert sum(zaehlung.values()) == len(leads)
    hoch = sum(1 for l in leads if l.get("kaufbereitschaft_stufe") == "hoch")
    assert hoch == zaehlung[pg.PREMIUM]  # nur PREMIUM darf „hoch" tragen
