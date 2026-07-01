"""Tests für die Kontakt-Anreicherung (Weg-2-Tiefe). Deterministisch, kein Netz.

Standalone:  PYTHONUTF8=1 PYTHONPATH=. python product/bridge/test_signal_contact_enrich.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from product.bridge import signal_contact_enrich as ce  # noqa: E402


# ─── parse_phone_de: echte Impressum-Strings + Falschtreffer-Schutz ──────────

def test_parse_phone_echtes_impressum_softgarden():
    txt = ("Impressum softgarden e-recruiting GmbH Tauentzienstraße 14 10789 Berlin "
           "Tel: +49 (0)30 884 940 400 Fax: +49 (0)30 884 940 401 E-Mail: info@softgarden.de")
    p = ce.parse_phone_de(txt)
    assert p.startswith("+49") and len(p) >= 12, p


def test_parse_phone_echtes_impressum_stroeer():
    txt = "Ströer-Allee 1 50999 Köln Telefon 02236 38696223 Umsatzsteuer-ID DE813895671"
    p = ce.parse_phone_de(txt)
    assert p.startswith("0") and "22363869" in p, p


def test_parse_phone_keine_falschtreffer():
    # USt-ID, HRB-Nummer, PLZ, Jahreszahl — NICHTS davon ist eine Telefonnummer.
    txt = ("Umsatzsteuer-Identifikationsnummer DE320212135 Registernummer: HRB 199 129 B "
           "10117 Berlin Copyright 2026 medialabel network gmbH")
    assert ce.parse_phone_de(txt) == "", ce.parse_phone_de(txt)


def test_parse_phone_leer():
    assert ce.parse_phone_de("") == ""
    assert ce.parse_phone_de("kein telefon hier, nur text") == ""


# ─── best_personal_email: Auswahl (KEINE Erfindung) ──────────────────────────

def test_best_personal_email_vorname_nachname():
    lead = {
        "contact_full_name": "Tivadar Szegeny",
        "email_pattern_suggestions": [
            "tivadar@medialabel.com", "tivadar.szegeny@medialabel.com",
            "t.szegeny@medialabel.com", "tivadar_szegeny@medialabel.com",
        ],
    }
    assert ce.best_personal_email(lead) == "tivadar.szegeny@medialabel.com"


def test_best_personal_email_ohne_vorschlaege():
    assert ce.best_personal_email({"contact_full_name": "Max Muster"}) == ""


def test_best_personal_email_ohne_name_kein_vorschlag():
    # Ohne Entscheidernamen KEIN Vorschlag (lieber nichts als eine Rollen-Adresse).
    lead = {"email_pattern_suggestions": ["a@x.de", "b@x.de"]}
    assert ce.best_personal_email(lead) == ""


def test_best_personal_email_rollenadresse_abgelehnt():
    # „webseiten@" darf NIE als persönlicher Vorschlag durchgehen (realer Fall HeyYou/Imago).
    lead = {
        "contact_full_name": "Sven Beispiel",
        "email_pattern_suggestions": ["webseiten@heyyoumarketing.de", "info@heyyoumarketing.de"],
    }
    assert ce.best_personal_email(lead) == ""


def test_best_personal_email_nur_vorname_matcht():
    # „nikita@" matcht den Vornamen (realer Fall Fahrengold).
    lead = {
        "contact_full_name": "Nikita Fahrengold",
        "email_pattern_suggestions": ["nikita@fahrengold.com"],
    }
    assert ce.best_personal_email(lead) == "nikita@fahrengold.com"


# ─── anreichern: in-place, defensiv, kein Auto-Send ──────────────────────────

def test_anreichern_telefon_aus_text():
    lead = {
        "phone": "", "website": "https://x.de", "email": "info@x.de",
        "impressum_info": "Musterstr 1 50667 Köln Telefon 0221 12345678 E-Mail info@x.de",
    }
    stats = ce.anreichern([lead])
    assert lead.get("phone") and lead.get("has_phone") is True, lead.get("phone")
    assert lead.get("kontakt_anreicherung") == "telefon_aus_text"
    assert stats["telefon_aus_text"] == 1


def test_anreichern_mail_vorschlag_nicht_in_email():
    lead = {
        "phone": "+4930123456", "email": "info@x.de",
        "contact_full_name": "Max Muster",
        "email_pattern_suggestions": ["max.muster@x.de", "m.muster@x.de"],
    }
    stats = ce.anreichern([lead])
    assert lead.get("persoenliche_mail_vorschlag") == "max.muster@x.de"
    assert lead["email"] == "info@x.de"  # email NICHT überschrieben (kein Auto-Send)
    assert stats["mail_vorschlag"] == 1


def test_anreichern_laesst_vorhandenes_telefon_in_ruhe():
    lead = {"phone": "+49 30 123456", "email": "max@x.de", "impressum_info": "Tel 0221 99999999"}
    ce.anreichern([lead])
    assert lead["phone"] == "+49 30 123456"  # unverändert
    assert "persoenliche_mail_vorschlag" not in lead  # email nicht generisch → kein Vorschlag


def test_anreichern_opt_in_live_sucher():
    # Kein Telefon im Text → injizierter Sucher liefert es (Live-Pfad, hier gefakt).
    lead = {"phone": "", "website": "https://x.de", "email": "info@x.de", "impressum_info": ""}
    stats = ce.anreichern([lead], telefon_sucher=lambda l: "Rückruf unter 0151 28141644 möglich")
    assert lead.get("phone") and lead.get("kontakt_anreicherung") == "telefon_live"
    assert stats["telefon_live"] == 1


def test_anreichern_defensiv_kein_crash():
    # Müll-Einträge dürfen den Lauf nicht kippen.
    stats = ce.anreichern([None, "kaputt", 123, {"email": "info@x.de"}])
    assert isinstance(stats, dict)


# ─── _ist_mull_name: Müll-Namen-Erkennung ────────────────────────────────────

def test_mull_name_adobe_fonts():
    assert ce._ist_mull_name("Adobe Fonts") is True


def test_mull_name_google_inc():
    assert ce._ist_mull_name("Google Inc") is True


def test_mull_name_cloudflare():
    assert ce._ist_mull_name("Cloudflare Inc") is True


def test_mull_name_rechtstext_zu_lang():
    assert ce._ist_mull_name("ABSCHNITT 5 DER DATENSCHUTZVERORDNUNG ERKLAERUNG") is True


def test_mull_name_mit_ziffer():
    assert ce._ist_mull_name("Max Muster123") is True


def test_mull_name_leer():
    assert ce._ist_mull_name("") is False
    assert ce._ist_mull_name(None) is False


def test_mull_name_echter_name_bleibt():
    for name in ("Jens Thiele", "Angela Bisping", "Gerhard Lütje", "Markus Ettlin",
                 "Jörg Jacobi", "Gerald Holler"):
        assert ce._ist_mull_name(name) is False, f"falscher Treffer: {name}"


# ─── anreichern: Müll-Namen werden bereinigt ────────────────────────────────

def test_anreichern_bereinigt_mull_namen():
    lead = {
        "phone": "", "email": "info@kisico.de",
        "managing_director": "Adobe Fonts",
        "contact_person": "Google Inc",
    }
    stats = ce.anreichern([lead])
    assert lead["managing_director"] == ""
    assert lead["contact_person"] == ""
    assert stats.get("mull_namen_bereinigt", 0) >= 2


def test_anreichern_behaelt_echte_namen():
    lead = {
        "phone": "", "email": "info@firma.de",
        "managing_director": "Jens Thiele",
        "contact_full_name": "Angela Bisping",
    }
    ce.anreichern([lead])
    assert lead["managing_director"] == "Jens Thiele"
    assert lead["contact_full_name"] == "Angela Bisping"


# ─── Schritt 3: erweiterte Artefakt-Erkennung (Name/Firma/Domain) ────────────

def test_mull_name_titelrest_ohne_namen():
    # „Parmentier Dipl" = Titelrest ohne echten Vor-+Nachnamen → Artefakt.
    assert ce._ist_mull_name("Parmentier Dipl") is True


def test_mull_name_echter_titel_bleibt():
    # „Dr. Hans Müller" / „Dipl.-Ing. Anna Schmidt" haben echten Namen → behalten.
    assert ce._ist_mull_name("Dr. Hans Müller") is False
    assert ce._ist_mull_name("Dipl.-Ing. Anna Schmidt") is False


def test_mull_name_verirrte_rechtsform_token():
    assert ce._ist_mull_name("Firmenname B2B") is True
    assert ce._ist_mull_name("Amercia Inc") is True


def test_mull_firma_platzhalter():
    assert ce._ist_mull_firma("Amercia Inc") is True
    assert ce._ist_mull_firma("Firmenname B2B") is True
    assert ce._ist_mull_firma("B2B") is True
    assert ce._ist_mull_firma("Musterfirma GmbH") is True


def test_mull_firma_echte_firma_bleibt():
    for f in ("Echte Maschinenbau GmbH", "3M Deutschland GmbH", "ACME B2B Solutions GmbH",
              "Streif Haus GmbH", "ISGUS GmbH"):
        assert ce._ist_mull_firma(f) is False, f


def test_platzhalter_domain():
    assert ce._ist_platzhalter_domain("https://info.yourdomain.com") is True
    assert ce._ist_platzhalter_domain("https://example.com") is True
    assert ce._ist_platzhalter_domain("https://www.echte-firma.de") is False
    assert ce._ist_platzhalter_domain("") is False


def test_anreichern_flaggt_firma_artefakt():
    leads = [
        {"company_name": "Amercia Inc", "website": "https://x.de", "email": "info@x.de"},
        {"company_name": "Gute Firma GmbH", "website": "https://info.yourdomain.com", "email": "info@x.de"},
        {"company_name": "Echte Maschinenbau GmbH", "website": "https://echt.de", "email": "info@x.de"},
    ]
    stats = ce.anreichern(leads)
    assert leads[0].get("company_name_artefakt") is True      # Artefakt-Firmenname
    assert leads[1].get("company_name_artefakt") is True      # Platzhalter-Domain
    assert not leads[2].get("company_name_artefakt")          # sauber
    assert stats["firma_artefakt"] == 2


# ─── _domain: Domain aus Website ─────────────────────────────────────────────

def test_domain_aus_website():
    assert ce._domain("https://www.Firma.de/impressum") == "firma.de"
    assert ce._domain("http://beispiel.com") == "beispiel.com"
    assert ce._domain("") == ""


# ─── Entscheider-Anreicherung (OPT-IN, injizierter Fake-Sucher, kein Netz) ────

def _fake_person(**felder):
    """Baut einen person_sucher, der ein festes dict liefert."""
    return lambda lead: dict(felder)


def test_person_enrichment_fuellt_leeren_namen():
    lead = {"website": "https://firma.de", "email": "info@firma.de"}
    sucher = _fake_person(name="Petra Klein", linkedin_url="https://linkedin.com/in/petra",
                          phone="+49 30 111", email="petra.klein@firma.de", title="Vertriebsleiterin")
    stats = ce.anreichern([lead], person_sucher=sucher)
    assert lead["managing_director"] == "Petra Klein"
    assert lead["contact_full_name"] == "Petra Klein"
    assert lead["linkedin_person_url"] == "https://linkedin.com/in/petra"
    assert lead["persoenliche_mail_vorschlag"] == "petra.klein@firma.de"
    assert lead["kontakt_anreicherung"] == "person_pdl"
    assert stats["person_angereichert"] == 1


def test_person_enrichment_ueberschreibt_vorhandenen_namen_nicht():
    lead = {"website": "https://firma.de", "email": "info@firma.de", "managing_director": "Jens Thiele"}
    sucher = _fake_person(name="Wer Anders")
    stats = ce.anreichern([lead], person_sucher=sucher)
    assert lead["managing_director"] == "Jens Thiele"  # unverändert
    assert stats["person_angereichert"] == 0


def test_person_enrichment_ohne_website_kein_call():
    def _explodiert(lead):
        raise AssertionError("person_sucher darf ohne Website nicht aufgerufen werden")
    lead = {"email": "info@firma.de"}  # keine website
    ce.anreichern([lead], person_sucher=_explodiert)  # darf nicht crashen
    assert "managing_director" not in lead or not lead.get("managing_director")


def test_person_enrichment_defensiv_bei_fehler():
    def _explodiert(lead):
        raise RuntimeError("API down")
    lead = {"website": "https://firma.de", "email": "info@firma.de"}
    stats = ce.anreichern([lead], person_sucher=_explodiert)  # Fehler geschluckt
    assert stats["person_angereichert"] == 0


def test_person_enrichment_aus_per_default():
    # Ohne person_sucher (= kein Key) passiert NICHTS Kostenpflichtiges.
    lead = {"website": "https://firma.de", "email": "info@firma.de"}
    stats = ce.anreichern([lead])
    assert stats["person_angereichert"] == 0
    assert not lead.get("managing_director")


def test_person_enrichment_mull_name_abgelehnt():
    # Selbst die teure Quelle darf keinen Garbage-Namen setzen.
    lead = {"website": "https://firma.de", "email": "info@firma.de"}
    stats = ce.anreichern([lead], person_sucher=_fake_person(name="Google Inc"))
    assert not lead.get("managing_director")
    assert stats["person_angereichert"] == 0


# ─── Fake-Nummer-Filter (2026-07-01) ────────────────────────────────────────
def test_ist_plausible_telefonnummer_fake_nullen():
    # real gesehen: Riso-Lead mit langem Nullen-Lauf
    assert ce.ist_plausible_telefonnummer("+4900000001728") is False
    assert ce.ist_plausible_telefonnummer("1111111111") is False        # nur 1 Ziffer
    assert ce.ist_plausible_telefonnummer("+490000") is False           # zu kurz


def test_ist_plausible_telefonnummer_echte_nummern():
    assert ce.ist_plausible_telefonnummer("+4954196310") is True
    assert ce.ist_plausible_telefonnummer("+49 221 6430460") is True
    assert ce.ist_plausible_telefonnummer("+4986544750") is True


def test_parse_phone_verwirft_fake_nummer():
    assert ce.parse_phone_de("Tel: +4900000001728") == ""
    assert ce.parse_phone_de("Fon 0000000000") == ""


def test_anreichern_leert_unplausible_vorhandene_nummer():
    lead = {"phone": "+4900000001728", "phone_clean": "+4900000001728", "has_phone": True}
    stats = ce.anreichern([lead])
    # Fake-Nummer entfernt (kein Text mit Ersatz -> bleibt leer)
    assert not lead.get("phone"), lead.get("phone")
    assert lead.get("has_phone") is False
    assert stats["telefon_unplausibel_geleert"] == 1


# ─── Namens-Artefakt-Bereinigung (2026-07-01) ───────────────────────────────
def test_kuerze_namen_artefakt_firmenstruktur():
    assert ce._kuerze_namen_artefakt("Marius Heinze Niederlassungen") == "Marius Heinze"
    assert ce._kuerze_namen_artefakt("Harry Ritter Bankinstitut") == "Harry Ritter"
    assert ce._kuerze_namen_artefakt("Max Mustermann Vertrieb") == "Max Mustermann"


def test_kuerze_namen_artefakt_echte_namen_unberuehrt():
    assert ce._kuerze_namen_artefakt("Udo Wenker") == "Udo Wenker"
    assert ce._kuerze_namen_artefakt("Gerald Holler") == "Gerald Holler"
    assert ce._kuerze_namen_artefakt("Anna Bankert") == "Anna Bankert"   # kein "bank"-Fehlschnitt


def test_anreichern_kuerzt_und_leert_namen():
    lead1 = {"contact_full_name": "Marius Heinze Niederlassungen", "website": "x.de"}
    lead2 = {"contact_full_name": "Zentrale Niederlassung Bayern", "website": "y.de"}
    stats = ce.anreichern([lead1, lead2])
    assert lead1["contact_full_name"] == "Marius Heinze"        # gekürzt, echter Name bleibt
    assert not lead2.get("contact_full_name")                   # reiner Struktur-Müll -> leer
    assert stats["namen_artefakt_gekuerzt"] >= 1
    assert stats["mull_namen_bereinigt"] >= 1


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
