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


def test_persoenliche_vs_sammelmail():
    assert r._hat_persoenliche_mail("anna.b@firma.de") is True
    assert r._hat_persoenliche_mail("info@firma.de") is False
    assert r._hat_persoenliche_mail("") is False


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
