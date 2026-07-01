"""Tests für product.bridge.clay_export."""
from __future__ import annotations

import json

from product.bridge import clay_export as ce


# ─── domain_aus_website ───────────────────────────────────────────────────────

def test_domain_standard():
    assert ce.domain_aus_website("https://www.itebo.de/unternehmen") == "itebo.de"


def test_domain_ohne_www_ohne_scheme():
    assert ce.domain_aus_website("compris-sales.de") == "compris-sales.de"


def test_domain_mit_port_und_gross():
    assert ce.domain_aus_website("HTTP://WWW.Beispiel.DE:8080/x") == "beispiel.de"


def test_domain_leer():
    assert ce.domain_aus_website("") == ""
    assert ce.domain_aus_website(None) == ""  # type: ignore[arg-type]


# ─── namen_split ──────────────────────────────────────────────────────────────

def test_namen_split_zwei():
    assert ce.namen_split("Udo Wenker") == ("Udo", "Wenker")


def test_namen_split_ein_token():
    assert ce.namen_split("Madonna") == ("Madonna", "")


def test_namen_split_drei():
    # Erster + letzter Token (robust für Enrichment-Match).
    assert ce.namen_split("Hans Peter Müller") == ("Hans", "Müller")


def test_namen_split_leer():
    assert ce.namen_split("") == ("", "")
    assert ce.namen_split("   ") == ("", "")


# ─── lead_zu_clay_zeile ───────────────────────────────────────────────────────

def _lead(**extra) -> dict:
    base = {
        "company_name": "Itebo",
        "website": "https://www.itebo.de/unternehmen",
        "city": "Osnabrück",
        "email": "udo.wenker@itebo.de",
        "phone": "+4954196310",
        "contact_full_name": "Udo Wenker",
        "linkedin_person_url": "https://de.linkedin.com/in/udowenker",
        "entdeckt_per_signal": "sales_hiring",
        "signal_quelle_url": "https://stepstone.de/x",
        "lead_id": "run123#0",
    }
    base.update(extra)
    return base


def test_zeile_hat_alle_vertragsspalten():
    z = ce.lead_zu_clay_zeile(_lead())
    assert set(z.keys()) == set(ce.CLAY_SPALTEN)


def test_zeile_werte_korrekt():
    z = ce.lead_zu_clay_zeile(_lead())
    assert z["lead_id"] == "run123#0"
    assert z["domain"] == "itebo.de"
    assert z["first_name"] == "Udo" and z["last_name"] == "Wenker"
    assert z["full_name"] == "Udo Wenker"
    assert z["role_email"] == "udo.wenker@itebo.de"
    assert z["central_phone"] == "+4954196310"
    assert z["signal"] == "sales_hiring"


def test_zeile_lead_id_fallback_aus_run_id_und_index():
    z = ce.lead_zu_clay_zeile({"company_name": "X", "run_id": "abc"}, index=4)
    assert z["lead_id"] == "abc#4"


def test_zeile_ohne_ansprechpartner_leere_namen():
    z = ce.lead_zu_clay_zeile(_lead(contact_full_name="", managing_director=""))
    assert z["first_name"] == "" and z["last_name"] == "" and z["full_name"] == ""


def test_zeile_nutzt_managing_director_als_fallback():
    z = ce.lead_zu_clay_zeile(_lead(contact_full_name="", managing_director="Frank Kamischke"))
    assert z["full_name"] == "Frank Kamischke"


def test_zeile_canonical_name_bevorzugt():
    z = ce.lead_zu_clay_zeile(_lead(canonical_company_name="Itebo GmbH"))
    assert z["company_name"] == "Itebo GmbH"


# ─── lade_leads / leads_zu_csv ────────────────────────────────────────────────

def test_lade_leads_dict_form(tmp_path):
    p = tmp_path / "run.json"
    p.write_text(json.dumps({"leads": [_lead()]}), encoding="utf-8")
    assert len(ce.lade_leads(p)) == 1


def test_lade_leads_listen_form(tmp_path):
    p = tmp_path / "list.json"
    p.write_text(json.dumps([_lead(), _lead()]), encoding="utf-8")
    assert len(ce.lade_leads(p)) == 2


def test_leads_zu_csv_schreibt_header_und_zeilen(tmp_path):
    ziel = tmp_path / "out.csv"
    n = ce.leads_zu_csv([_lead(), _lead(lead_id="run123#1")], ziel)
    assert n == 2
    text = ziel.read_text(encoding="utf-8-sig")
    zeilen = [z for z in text.splitlines() if z.strip()]
    assert zeilen[0].startswith("lead_id,company_name,domain")
    assert len(zeilen) == 3  # Header + 2 Leads
    assert "itebo.de" in text


def test_leads_zu_csv_leer(tmp_path):
    ziel = tmp_path / "leer.csv"
    n = ce.leads_zu_csv([], ziel)
    assert n == 0
    assert ziel.exists()  # nur Header


# ─── ist_persoenliche_mail / hat_persoenliche_mail (Rollen-Postfach-Gate) ─────

def test_ist_persoenliche_mail_echte_person():
    for addr in ["t.heyen@personal-holding.de", "Marco.Schubert@elflein.de",
                 "markus.steinke@warumbkv.de", "g.tschacher@bav-ingenieure.de",
                 "christian.viertel@viertel-motoren.de", "c.arora@pinguin-system.de",
                 "anne-marie.schmidt@x.de"]:
        assert ce.ist_persoenliche_mail(addr) is True, addr


def test_ist_persoenliche_mail_rollen_und_abteilung():
    for addr in ["info@enigmania.de", "technik@petec.de", "tankstellen@gascom.de",
                 "netzanschluesse@netz-leipzig.de", "hinweis@spedition-zurek.de",
                 "gruppe@schneiderworx.de", "shop@jobrad-loop.com",
                 "online-redaktion@leipzig.de", "duesseldorf@artus-sanierung.de",
                 "gf@pinguin-system.de", "kundenservice@x.de"]:
        assert ce.ist_persoenliche_mail(addr) is False, addr


def test_hat_persoenliche_mail_lead():
    assert ce.hat_persoenliche_mail({"email": "g.tschacher@bav-ingenieure.de"}) is True
    assert ce.hat_persoenliche_mail({"email": "technik@petec.de"}) is False
    assert ce.hat_persoenliche_mail({"email": ""}) is False
    assert ce.hat_persoenliche_mail({}) is False
