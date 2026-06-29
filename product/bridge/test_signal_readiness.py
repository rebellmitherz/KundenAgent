"""Tests für die Kaufbereitschafts-Analyse (signal_readiness) — deterministisch.

Standalone:  python product/bridge/test_signal_readiness.py
Pytest:      pytest product/bridge/test_signal_readiness.py
"""
from __future__ import annotations

from product.bridge import signal_readiness as r


def _lead(**kw) -> dict:
    base = {
        "entdeckt_per_signal": "sales_hiring",
        "signal_fit_score": 0.6,
        "contact_quality_score": 50,
        "email": "max.mustermann@firma.de",
        "phone": "+4951112345",
        "signal_titel": "Vertriebsmitarbeiter (m/w/d)",
        "signal_quelle_url": "https://stepstone.de/job/123",
    }
    base.update(kw)
    return base


def test_heisses_signal_voller_kontakt_ist_hoch():
    l = _lead(entdeckt_per_signal="appointment_setter", signal_fit_score=0.9,
              contact_quality_score=70, email="anna.b@firma.de", phone="+4951199")
    res = r.bewerten(l)
    assert res["score"] >= 70 and res["stufe"] == r.HOCH, res
    # Kaufsignal-Grund steht an erster Stelle, Beleg vorhanden.
    assert res["gruende"][0].startswith("Kaufsignal:")
    assert res["beleg_url"] == "https://stepstone.de/job/123"


def test_schwaches_signal_nur_sammelmail_ist_niedrig():
    l = _lead(entdeckt_per_signal="marketing_hiring", signal_fit_score=0.3,
              contact_quality_score=20, email="info@firma.de", phone="")
    res = r.bewerten(l)
    assert res["score"] < 45 and res["stufe"] == r.NIEDRIG, res
    # info@ zählt nicht als persönliche Mail, kein Telefon → keine Erreichbarkeits-Zeile
    assert not any("erreichbar" in g.lower() or "persönliche" in g.lower() for g in res["gruende"])


def test_signaltyp_ordnet_kaufbereitschaft():
    # Gleiche Firma/Kontakt, nur Signaltyp variiert → heißeres Signal = höherer Score.
    heiss = r.bewerten(_lead(entdeckt_per_signal="appointment_setter"))
    lau = r.bewerten(_lead(entdeckt_per_signal="new_location"))
    assert heiss["score"] > lau["score"], (heiss["score"], lau["score"])


def test_unbekanntes_signal_default_staerke():
    assert r._signal_staerke("voodoo") == 0.5
    assert r._signal_staerke("") == 0.5


# ─── Versicherungs-Signale (additiv) ─────────────────────────────────────────

def test_versicherungs_signale_haben_staerke_und_warum():
    from product.bridge import signal_discovery as sd
    for st in sd._VERSICHERUNGS_SIGNAL_TYPES:
        # echte Stärke (nicht der 0.5-Default) + kundenlesbare Begründung
        assert r._SIGNAL_STAERKE.get(st), st
        assert r._SIGNAL_WARUM.get(st), st


def test_vs_hiring_ist_heisses_versicherungssignal():
    # vs_hiring (führt zu wiederkehrender bAV) muss höher wiegen als z. B. vs_cyber.
    heiss = r.bewerten(_lead(entdeckt_per_signal="vs_hiring",
                             signal_titel="Mitarbeiter (m/w/d) gesucht"))
    lau = r.bewerten(_lead(entdeckt_per_signal="vs_cyber",
                           signal_titel="Softwareentwickler (m/w/d)"))
    assert heiss["score"] > lau["score"], (heiss["score"], lau["score"])
    # Kaufsignal-Begründung trägt den Versicherungs-Aufhänger.
    assert heiss["gruende"][0].startswith("Kaufsignal:")
    assert "bAV" in heiss["gruende"][0] or "Mitarbeiter" in heiss["gruende"][0]


def test_persoenliche_vs_sammelmail():
    # Klares vorname.nachname-Muster → persönlich.
    assert r.ist_persoenliche_mail("max.mustermann@firma.de") is True
    assert r.ist_persoenliche_mail("andrea.schmidt@firma.de") is True
    # Sammel-/Rollen-Postfächer → NIE persönlich (auch mit Trenner/Region/Ziffern).
    for sammel in ("info@firma.de", "kontakt@firma.de", "vertrieb@firma.de",
                   "bewerbung@firma.de", "info.berlin@firma.de", "info.de@firma.de",
                   "de.contact@firma.de", "datenschutz@firma.de", "noreply@firma.de"):
        assert r.ist_persoenliche_mail(sammel) is False, sammel
    # firstname.initial: nur mit bekanntem Ansprechpartner sicher persönlich,
    # sonst konservativ (lieber kein Etikett als ein falsches).
    assert r.ist_persoenliche_mail("anna.b@firma.de") is False
    assert r.ist_persoenliche_mail("anna.b@firma.de", "Anna Bauer") is True
    # vorname.nachname@, aber bekannter Ansprechpartner ist eine ANDERE Person
    # → gehört nicht unserem Kontakt → NICHT als persönlicher Kanal werten.
    assert r.ist_persoenliche_mail("andy.freund@firma.de", "Michael Petri") is False
    # Passt der Name dagegen, bleibt es persönlich.
    assert r.ist_persoenliche_mail("andy.freund@firma.de", "Andy Freund") is True
    # Bloßer Vorname / Kürzel ohne Namensbeleg → nicht persönlich.
    assert r.ist_persoenliche_mail("markus@firma.de") is False
    assert r.ist_persoenliche_mail("t.online@firma.de") is False
    assert r.ist_persoenliche_mail("") is False
    # Rückwärtskompatibler Alias.
    assert r._hat_persoenliche_mail("info@firma.de") is False
    # Mobilnummer-Erkennung (DE-Mobilfunk = Direktkontakt, Festnetz/Ausland nicht).
    assert r.ist_mobilnummer("0171 1234567") is True
    assert r.ist_mobilnummer("+49 151 1234567") is True
    assert r.ist_mobilnummer("030 1234567") is False
    assert r.ist_mobilnummer("") is False


def test_frische_senkt_altes_signal():
    # Gleicher Lead, einmal frisch, einmal >90 Tage alt → alt hat klar weniger Score.
    frisch = r.bewerten(_lead(signal_alter_tage=3))
    alt = r.bewerten(_lead(signal_alter_tage=200))
    assert frisch["score"] > alt["score"], (frisch["score"], alt["score"])
    # Frisches Signal nennt die Anzeige als Verkaufsargument …
    assert any("frisch" in g.lower() for g in frisch["gruende"]), frisch["gruende"]
    # … altes Signal warnt ehrlich.
    assert any("aktualität" in g.lower() or "⚠" in g for g in alt["gruende"]), alt["gruende"]


def test_frische_unbekannt_kein_abschlag():
    # Ohne signal_alter_tage darf sich gegenüber „frisch" nichts ändern (Faktor 1.0).
    ohne = r.bewerten(_lead())
    frisch = r.bewerten(_lead(signal_alter_tage=5))
    assert ohne["score"] == frisch["score"], (ohne["score"], frisch["score"])


def test_anreichern_setzt_frische_felder():
    leads = [_lead(signal_alter_tage=3)]
    r.anreichern(leads)
    assert leads[0]["signal_alter_tage"] == 3
    assert leads[0]["signal_frische_text"] == "vor 3 Tagen"


def test_anreichern_schreibt_alle_felder():
    leads = [_lead(), {"company_name": "Leer"}]  # zweiter ohne Signal/Kontakt
    r.anreichern(leads)
    for l in leads:
        assert "kaufbereitschaft_score" in l
        assert "kaufbereitschaft_stufe" in l
        assert isinstance(l["kaufbereitschaft_gruende"], list)
        assert "kaufbereitschaft_beleg_url" in l
    # Der leere Lead darf nicht crashen und bekommt eine niedrige Stufe.
    assert leads[1]["kaufbereitschaft_stufe"] in (r.HOCH, r.MITTEL, r.NIEDRIG)


def test_anreichern_defensiv_bei_muellwerten():
    leads = [{"entdeckt_per_signal": "sales_hiring", "signal_fit_score": "abc",
              "contact_quality_score": None}]
    r.anreichern(leads)  # darf nicht werfen
    assert 0 <= leads[0]["kaufbereitschaft_score"] <= 100


def test_stapelung_hebt_score_und_gibt_heissgrad_grund():
    base = {"signal_fit_score": 0.6, "contact_quality_score": 50, "phone": "+4955",
            "email": "max.muster@x.de", "signal_titel": "X", "signal_quelle_url": "https://x/j"}
    ein = r.bewerten({**base, "entdeckt_per_signal": "sales_hiring", "signale": ["sales_hiring"]})
    drei = r.bewerten({**base, "entdeckt_per_signal": "sales_hiring",
                       "signale": ["sales_hiring", "appointment_setter", "growth_expansion"]})
    assert drei["score"] > ein["score"]                       # Stapelung hebt
    assert "gleichzeitige" in drei["gruende"][0]              # Heißgrad-Grund zuerst
    assert "gleichzeitige" not in ein["gruende"][0]


def test_stapel_bonus_gedeckelt_und_geklemmt():
    base = {"signal_fit_score": 0.9, "contact_quality_score": 90, "phone": "+4955",
            "email": "max.muster@x.de"}
    fuenf = r.bewerten({**base, "entdeckt_per_signal": "appointment_setter",
                        "signale": ["appointment_setter", "sales_hiring", "growth_expansion",
                                    "marketing_hiring", "new_location"]})
    assert fuenf["score"] <= 100                              # nie über 100


# ── Schritt 2: Engine-Härtung (Deckelung) ──────────────────────────────────
def test_ready_to_send_no_deckelt_auf_mittel():
    # Heißes Signal + voller Kontakt = wäre „hoch", aber Engine sagt nicht sendefähig.
    l = _lead(entdeckt_per_signal="appointment_setter", signal_fit_score=0.9,
              contact_quality_score=90, email="anna.bauer@firma.de", phone="0171 1234567",
              ready_to_send="no", ready_to_send_block_reason="email_quality_review_required")
    res = r.bewerten(l)
    assert res["stufe"] != r.HOCH, res            # nie „hoch"
    assert res["score"] <= 60
    assert any("sendefähig" in g.lower() for g in res["gruende"]), res["gruende"]


def test_ready_to_send_yes_bleibt_unangetastet():
    l = _lead(entdeckt_per_signal="appointment_setter", signal_fit_score=0.9,
              contact_quality_score=90, email="anna.bauer@firma.de", phone="0171 1234567",
              ready_to_send="yes")
    res = r.bewerten(l)
    assert res["stufe"] == r.HOCH, res            # gutes Urteil bleibt hoch


def test_do_not_contact_macht_niedrig():
    l = _lead(entdeckt_per_signal="appointment_setter", signal_fit_score=0.9,
              contact_quality_score=90, phone="0171 1234567", do_not_contact=True)
    res = r.bewerten(l)
    assert res["stufe"] == r.NIEDRIG and res["score"] <= 25, res
    assert any("do_not_contact" in g.lower() for g in res["gruende"])


def test_fake_mail_rang_senkt_score():
    gut = r.bewerten(_lead(email_quality_rank="A"))
    fake = r.bewerten(_lead(email_quality_rank="D"))
    assert fake["score"] < gut["score"], (fake["score"], gut["score"])
    assert any("rang d" in g.lower() for g in fake["gruende"]), fake["gruende"]


def test_rollenmail_ohne_telefon_nie_hoch():
    # info@ + kein Telefon: selbst bei heißem Signal/hohem Fit max. mittel.
    l = _lead(entdeckt_per_signal="appointment_setter", signal_fit_score=0.9,
              contact_quality_score=90, email="info@firma.de", phone="")
    res = r.bewerten(l)
    assert res["stufe"] != r.HOCH, res


def test_haertung_ohne_enginefelder_unveraendert():
    # Ohne ready_to_send/Rang/do_not_contact ändert sich nichts (Rückwärtskompat).
    l = _lead(entdeckt_per_signal="appointment_setter", signal_fit_score=0.9,
              contact_quality_score=90, email="anna.bauer@firma.de", phone="0171 1234567")
    res = r.bewerten(l)
    assert res["stufe"] == r.HOCH and res["score"] >= 70, res


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
    import sys
    sys.exit(0 if _run_all() else 1)
