"""Tests für clay_import (Merge-back der Clay-CSV auf die Leads)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from product.bridge import clay_import as ci  # noqa: E402


# ─── Spalten-Erkennung (robust gegen Clays reale Namen) ─────────────────────
def test_norm_header():
    assert ci._norm_header("Work Email") == "work_email"
    assert ci._norm_header("Mobile Number ") == "mobile_number"
    assert ci._norm_header("Email-Status") == "email_status"


def test_spalten_map_erkennt_gaengige_clay_namen():
    header = ["lead_id", "domain", "Work Email", "Mobile Number", "Email Status"]
    smap = ci.spalten_map(header)
    assert smap["personal_email"] == "Work Email"
    assert smap["mobile_phone"] == "Mobile Number"
    assert smap["email_status"] == "Email Status"
    assert smap["domain"] == "domain"


def test_spalten_map_alternative_namen():
    header = ["lead_id", "company_domain", "Verified Email", "Direct Dial"]
    smap = ci.spalten_map(header)
    assert smap["personal_email"] == "Verified Email"
    assert smap["mobile_phone"] == "Direct Dial"
    assert smap["domain"] == "company_domain"


# ─── Merge: nur Kontaktfelder, Premium-Felder unberührt ─────────────────────
def _leads():
    return [
        {"website": "https://www.itebo.de/x", "company_name": "Itebo", "email": "info@itebo.de",
         "briefing": {"kurzprofil": "X"}, "premium_klasse": "PREMIUM", "kaufbereitschaft_score": 75},
        {"website": "https://sanitaer-heinze.com", "company_name": "Bautzen", "email": "info@sanitaer-heinze.com",
         "briefing": {"kurzprofil": "Y"}, "premium_klasse": "PREMIUM"},
    ]


def test_merge_kontakt_setzt_nur_kontaktfelder():
    leads = _leads()
    header = ["domain", "Work Email", "Mobile Number", "Email Status"]
    enriched = [
        {"domain": "itebo.de", "Work Email": "udo.wenker@itebo.de",
         "Mobile Number": "+4915112345678", "Email Status": "valid"},
    ]
    stats = ci.merge_kontakt(leads, enriched, ci.spalten_map(header))
    it = leads[0]
    assert it["clay_personal_email"] == "udo.wenker@itebo.de"
    assert it["email"] == "udo.wenker@itebo.de"           # generisch -> gehoben
    assert it["is_generic_email"] is False
    assert it["mobile_phone"] == "+4915112345678"
    assert it["clay_email_status"] == "valid"
    # Premium-Inhalt UNBERÜHRT:
    assert it["briefing"] == {"kurzprofil": "X"}
    assert it["premium_klasse"] == "PREMIUM"
    assert it["kaufbereitschaft_score"] == 75
    assert stats["gematcht"] == 1 and stats["pers_mail_gesetzt"] == 1


def test_merge_ignoriert_generische_clay_mail():
    leads = _leads()
    enriched = [{"domain": "itebo.de", "Work Email": "info@itebo.de"}]
    ci.merge_kontakt(leads, enriched, ci.spalten_map(["domain", "Work Email"]))
    assert "clay_personal_email" not in leads[0]           # generische Mail wird nicht gesetzt


def test_merge_ohne_domain_match():
    leads = _leads()
    enriched = [{"domain": "fremde-firma.de", "Work Email": "a.b@fremde-firma.de"}]
    stats = ci.merge_kontakt(leads, enriched, ci.spalten_map(["domain", "Work Email"]))
    assert stats["ohne_match"] == 1 and stats["gematcht"] == 0


# ─── Kanal-Gate ─────────────────────────────────────────────────────────────
def test_ist_auslieferbar():
    assert ci.ist_auslieferbar({"email": "max.mueller@firma.de"}) is True        # pers. Mail
    assert ci.ist_auslieferbar({"email": "info@firma.de", "phone": "+4954196310"}) is True  # Zentrale ok
    assert ci.ist_auslieferbar({"email": "info@firma.de", "mobile_phone": "+4915112345678"}) is True
    assert ci.ist_auslieferbar({"email": "info@firma.de", "phone": "+4900000001728"}) is False  # Fake + generisch
    assert ci.ist_auslieferbar({"email": "info@firma.de"}) is False              # nur generisch, kein Tel


def test_merge_und_filtern_sortiert_kanallos_aus():
    leads = _leads()
    # Itebo bekommt pers. Mail, Bautzen bleibt bei info@ ohne Telefon -> raus.
    enriched = [{"domain": "itebo.de", "Work Email": "udo.wenker@itebo.de"}]
    auslieferbar, stats = ci.merge_und_filtern(leads, enriched, ci.spalten_map(["domain", "Work Email"]))
    namen = {l["company_name"] for l in auslieferbar}
    assert namen == {"Itebo"}
    assert stats["auslieferbar"] == 1 and stats["aussortiert_kein_kanal"] == 1


# ─── CSV-Laden (BOM, Semikolon) ─────────────────────────────────────────────
def test_lade_enriched_csv_semikolon_und_bom(tmp_path):
    p = tmp_path / "enriched.csv"
    p.write_text("﻿domain;Work Email;Mobile Number\nitebo.de;udo@itebo.de;+4915112345678\n",
                 encoding="utf-8")
    zeilen, smap = ci.lade_enriched_csv(p)
    assert len(zeilen) == 1
    assert smap["personal_email"] == "Work Email"
    assert zeilen[0]["domain"] == "itebo.de"
