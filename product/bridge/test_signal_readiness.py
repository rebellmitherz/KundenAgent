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
