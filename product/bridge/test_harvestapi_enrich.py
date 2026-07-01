"""Tests für harvestapi_enrich (Mail-Anreicherung via Apify-Actor).

Kein Netz: der Actor-Aufruf wird über ``runner`` injiziert.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from product.bridge import harvestapi_enrich as he  # noqa: E402


# ─── URL-Normalisierung (de. vs www. muss matchen) ──────────────────────────
def test_norm_li_ignoriert_subdomain_und_schema():
    a = he._norm_li("https://de.linkedin.com/in/arora-123")
    b = he._norm_li("https://www.linkedin.com/in/arora-123/")
    c = he._norm_li("http://linkedin.com/in/arora-123?trk=x")
    assert a == b == c == "/in/arora-123"


# ─── Mail-Auswahl + Domain-Gate ─────────────────────────────────────────────
def test_beste_email_nimmt_domain_treffer_valide():
    emails = [
        {"email": "info@pinguin-system.de", "status": "valid"},            # generisch -> raus
        {"email": "c.arora@fremd.de", "status": "valid"},                  # falsche Domain -> raus
        {"email": "c.arora@pinguin-system.de", "status": "valid",
         "deliverable": True, "catchAllDomain": False, "qualityScore": 80},
    ]
    best = he.beste_email(emails, "pinguin-system.de")
    assert best["email"] == "c.arora@pinguin-system.de"


def test_beste_email_domain_mismatch_gibt_none():
    emails = [{"email": "nikolas@consilium-sv.de", "status": "risky",
               "catchAllDomain": True, "qualityScore": 60}]
    assert he.beste_email(emails, "sanierungsservice.de") is None


def test_beste_email_leer():
    assert he.beste_email([], "firma.de") is None


# ─── Voll-Merge über emails_fuer_leads ──────────────────────────────────────
def _leads():
    return [
        # A: URL + generische Mail -> soll persoenliche Mail bekommen
        {"company_name": "Pinguin", "website": "https://pinguin-system.de",
         "email": "info@pinguin-system.de", "linkedin_person_url": "https://de.linkedin.com/in/arora-123",
         "briefing": {"kurzprofil": "X"}, "premium_klasse": "PREMIUM"},
        # B: URL + generische Mail, aber Fund ist falsche Domain -> KEINE Mail
        {"company_name": "Kuepper", "website": "https://sanierungsservice.de",
         "email": "info@sanierungsservice.de", "linkedin_person_url": "https://de.linkedin.com/in/nikolas-9"},
        # C: keine URL -> kein Kandidat
        {"company_name": "PETEC", "website": "https://petec.de", "email": "technik@petec.de"},
        # D: schon persoenliche Mail -> uebersprungen
        {"company_name": "Itebo", "website": "https://itebo.de", "email": "udo.wenker@itebo.de",
         "linkedin_person_url": "https://de.linkedin.com/in/udo-1"},
    ]


def _runner(urls, key):
    # simuliert harvestapi: liefert linkedinUrl in www-Form + emails
    return [
        {"linkedinUrl": "https://www.linkedin.com/in/arora-123", "firstName": "Christian",
         "lastName": "Arora", "emails": [
             {"email": "c.arora@pinguin-system.de", "status": "valid", "deliverable": True,
              "catchAllDomain": False, "free": False, "qualityScore": 80}]},
        {"linkedinUrl": "https://www.linkedin.com/in/nikolas-9", "firstName": "Nikolas",
         "lastName": "Mittelstedt", "emails": [
             {"email": "nikolas@consilium-sv.de", "status": "risky", "catchAllDomain": True,
              "qualityScore": 60}]},
    ]


def test_emails_fuer_leads_setzt_nur_domain_treffer():
    leads = _leads()
    stats = he.emails_fuer_leads(leads, runner=_runner, key="TESTKEY")
    a, b, c, d = leads
    # A: persoenliche Mail gesetzt + Quelle markiert
    assert a["email"] == "c.arora@pinguin-system.de"
    assert a["email_source_type"] == "harvestapi_enrichment"
    assert a["is_generic_email"] is False
    assert a["harvestapi_email_quality"] == 80
    # Premium-Inhalt unberuehrt
    assert a["briefing"] == {"kurzprofil": "X"} and a["premium_klasse"] == "PREMIUM"
    # B: falsche Domain -> Mail NICHT uebernommen (bleibt generisch), aber Name ergaenzt
    assert b["email"] == "info@sanierungsservice.de"
    assert "harvestapi_personal_email" not in b
    assert b["contact_full_name"] == "Nikolas Mittelstedt"
    # C/D: kein Kandidat / uebersprungen
    assert "harvestapi_personal_email" not in c and "harvestapi_personal_email" not in d
    assert stats["kandidaten"] == 2
    assert stats["mail_gesetzt"] == 1
    assert stats["ohne_treffer"] == 1
    assert stats["uebersprungen_hat_mail"] == 1


def test_kein_telefon_wird_gesetzt():
    """harvestapi ist Mail-only — es darf NIE ein Telefonfeld schreiben."""
    leads = _leads()
    he.emails_fuer_leads(leads, runner=_runner, key="TESTKEY")
    for l in leads:
        assert "mobile_phone" not in l and "direct_dial" not in l


def test_ohne_key_uebersprungen_ohne_crash(monkeypatch):
    # Kein Key nirgends (auch nicht in .env) -> Runner darf nie laufen.
    monkeypatch.setattr(he, "_apify_key", lambda: "")
    leads = _leads()
    calls = []
    def spy(urls, key):
        calls.append(urls); return []
    stats = he.emails_fuer_leads(leads, runner=spy)   # kein key -> Fallback _apify_key()=""
    assert "fehler" in stats and calls == []          # Runner nie aufgerufen


def test_runner_fehler_kippt_lauf_nicht():
    leads = _leads()
    def boom(urls, key):
        raise RuntimeError("HTTP 500")
    stats = he.emails_fuer_leads(leads, runner=boom, key="TESTKEY")
    assert "fehler" in stats and "HTTP 500" in stats["fehler"]
    # Leads unveraendert (keine Mail gesetzt)
    assert leads[0]["email"] == "info@pinguin-system.de"
