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


# ── Regel 5b: No-Sales-Postfächer (jobs@/helpdesk@/noreply@ …) ───────────────
@pytest.mark.parametrize("mail", [
    "jobs@echte-firma.de", "helpdesk@echte-firma.de", "bewerbung@echte-firma.de",
    "noreply@echte-firma.de", "datenschutz@echte-firma.de",
])
def test_no_sales_postfach_ohne_telefon_ist_reject(mail):
    # Einziger Kanal ist ein No-Sales-Postfach → nicht sendefähig.
    r = pg.bewerten_premium(_premium_lead(email=mail, phone=""), zielbranche="Maschinenbau")
    assert r["klasse"] == pg.REJECT


def test_no_sales_postfach_mit_telefon_nie_premium():
    # Mit Telefon nicht raus, aber der Mail-Kanal ist unbrauchbar → höchstens REVIEW.
    r = pg.bewerten_premium(_premium_lead(email="jobs@echte-firma.de"), zielbranche="Maschinenbau")
    assert r["klasse"] == pg.REVIEW


def test_soft_rollen_mail_mit_telefon_bleibt_premium_unveraendert():
    # Bewusste Abgrenzung: info@ ist nur „nicht persönlich", kein No-Sales-Postfach.
    # Mit Telefon (Mobil) bleibt der Lead PREMIUM — deckt sich mit dem Produktversprechen
    # „Telefon/Mobil ODER persönliche Mail".
    r = pg.bewerten_premium(_premium_lead(email="info@echte-firma.de"), zielbranche="Maschinenbau")
    assert r["klasse"] == pg.PREMIUM


# ── Regel 4b: Firmenname-Scrape-Artefakte ───────────────────────────────────
@pytest.mark.parametrize("firma", [
    "GmbH Unternehmensangaben ventx GmbH",   # echter Lauf: Rechtsform voran + Überschrift
    "Impressum Stuer GmbH",
    "GmbH ventx",                             # Rechtsform als erstes Wort
])
def test_firma_scrape_artefakt_ist_reject(firma):
    r = pg.bewerten_premium(_premium_lead(company_name=firma), zielbranche="Maschinenbau")
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


# ── ICP-Fit-Falle: breiter ICP (Versicherungsleads) ─────────────────────────
def test_icp_breit_branchenabweichung_rejectet_nicht():
    # Versicherung: der Trigger qualifiziert, nicht die enge Branche. Eine
    # Branchen-Abweichung darf den sonst sauberen Lead NICHT mehr rejecten.
    lead = _premium_lead(entdeckt_per_signal="vs_hiring", industry="Logistik",
                         description="Speditionsbetrieb", company_name="Echte Logistik GmbH")
    eng = pg.bewerten_premium(lead, zielbranche="Handwerk")
    breit = pg.bewerten_premium(lead, zielbranche="Handwerk", icp_breit=True)
    assert eng["klasse"] == pg.REJECT          # enger ICP wie bisher: hart raus
    assert breit["klasse"] == pg.PREMIUM       # breiter ICP: liefertbar


def test_icp_breit_unbestimmt_blockt_premium_nicht():
    # Ohne prüfbare Zielbranche (breiter ICP) darf der Lead trotzdem PREMIUM sein,
    # solange alle harten Regeln (Website/Kontakt/Frische/Beleg) erfüllt sind.
    lead = _premium_lead(entdeckt_per_signal="vs_fuhrpark", industry="Logistik")
    r = pg.bewerten_premium(lead, zielbranche="", icp_breit=True)
    assert r["klasse"] == pg.PREMIUM


def test_icp_breit_haelt_andere_harte_regeln():
    # Breiter ICP weicht NUR Regel 7 auf — die übrigen harten K.-o.-Gründe greifen weiter.
    ohne_web = pg.bewerten_premium(
        _premium_lead(entdeckt_per_signal="vs_hiring", website=""),
        zielbranche="Handwerk", icp_breit=True)
    assert ohne_web["klasse"] == pg.REJECT     # keine echte Website → trotzdem raus


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
    # Invariante: NUR PREMIUM darf „hoch" tragen (hoch ⊆ PREMIUM). Nicht jeder
    # PREMIUM-Lead ist „hoch" — bei unbekanntem Beleg-Datum deckelt das Gate auf
    # „mittel". Darum ist die korrekte Prüfung „jeder hoch-Lead ist PREMIUM" + hoch ≤ PREMIUM.
    hoch_leads = [l for l in leads if l.get("kaufbereitschaft_stufe") == "hoch"]
    assert all(l.get("premium_klasse") == pg.PREMIUM for l in hoch_leads)
    assert len(hoch_leads) <= zaehlung[pg.PREMIUM]
