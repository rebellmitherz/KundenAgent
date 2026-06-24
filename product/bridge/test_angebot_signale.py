"""Tests für die Angebot→Signal-Kopplung (additiver Bereich „Versicherungsleads").

Deterministisch, kein Netz. Sichert ab, dass sich die zwei Signal-Welten
(Vertrieb vs. Versicherung) sauber je Angebot trennen und nichts vermischt.

Standalone:  python product/bridge/test_angebot_signale.py
Pytest:      pytest product/bridge/test_angebot_signale.py
"""
from __future__ import annotations

from product.bridge import angebot_signale as a_s
from product.bridge import signal_discovery as sd
from product.personalization.aufhaenger import aufhaenger_text
from product.personalization.signal_outreach import angebot_aus_profil_id


def test_gruppe_fuer_angebot():
    # Versicherung wird über die ID erkannt (robust gegen Slug-Varianten).
    assert a_s.gruppe_fuer_angebot("versicherungsleads") == a_s.GRUPPE_VERSICHERUNG
    assert a_s.gruppe_fuer_angebot("versicherungs_leads") == a_s.GRUPPE_VERSICHERUNG
    # Alles andere bleibt Vertrieb (unverändert).
    for pid in ("kundenagent", "akquise", "website", "", "irgendwas"):
        assert a_s.gruppe_fuer_angebot(pid) == a_s.GRUPPE_VERTRIEB, pid


def test_signaltypen_fuer_angebot_trennt_welten():
    vertrieb = set(a_s.signaltypen_fuer_angebot("kundenagent"))
    versicherung = set(a_s.signaltypen_fuer_angebot("versicherungsleads"))
    assert vertrieb == set(sd._VERTRIEBS_SIGNAL_TYPES)
    assert versicherung == set(sd._VERSICHERUNGS_SIGNAL_TYPES)
    assert not (vertrieb & versicherung)   # keine Überschneidung


def test_ist_versicherungs_signalset():
    assert a_s.ist_versicherungs_signalset(["vs_hiring"]) is True
    assert a_s.ist_versicherungs_signalset(["sales_hiring", "vs_cyber"]) is True  # gemischt
    assert a_s.ist_versicherungs_signalset(["sales_hiring"]) is False
    assert a_s.ist_versicherungs_signalset([]) is False


def test_signal_meta_struktur_und_defaults():
    meta = a_s.signal_meta_fuer_angebot("versicherungsleads")
    assert [m["key"] for m in meta] == list(sd._VERSICHERUNGS_SIGNAL_TYPES)  # Reihenfolge = Gewichtung
    assert all(m["label"] for m in meta)                                     # Labels gesetzt
    assert [m["key"] for m in meta if m["hot"]] == ["vs_hiring"]             # heißeste Spur
    assert [m["key"] for m in meta if m["default"]]                         # mind. ein Default angehakt
    # Jeder gemeldete Key ist auch ein gültiger, bekannter Signaltyp.
    assert all(m["key"] in sd.SIGNAL_TYPES for m in meta)


def test_vertriebs_meta_unveraendert():
    # Das bisherige Vertriebs-Verhalten bleibt 1:1 (Pilot-Kaltakquise-Firma).
    meta = a_s.signal_meta_fuer_angebot("kundenagent")
    keys = [m["key"] for m in meta]
    assert keys == list(sd._VERTRIEBS_SIGNAL_TYPES)
    assert [m["key"] for m in meta if m["hot"]] == ["sales_hiring"]
    assert {m["key"] for m in meta if m["default"]} == {
        "sales_hiring", "appointment_setter", "growth_expansion"}


def test_versicherungs_profil_routet_auf_versicherungs_aufhaenger():
    assert angebot_aus_profil_id("versicherungsleads") == "versicherung"
    # Jedes vs_-Signal bringt einen fertigen Aufhänger-Satz (auch ohne LLM).
    for st in sd._VERSICHERUNGS_SIGNAL_TYPES:
        satz = aufhaenger_text({"entdeckt_per_signal": st}, "versicherung",
                               firma="Muster GmbH", branche="Logistik")
        assert satz and len(satz) > 20, st


def test_vertriebssignal_im_versicherungsangebot_kein_aufhaenger():
    # saubere Trennung: ein Vertriebs-Signal erzeugt im Versicherungs-Angebot
    # KEINEN (fremden) Aufhänger.
    assert aufhaenger_text({"entdeckt_per_signal": "sales_hiring"}, "versicherung") == ""


if __name__ == "__main__":
    import sys
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok  {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL  {name}: {e}")
    print("alle grün" if not fails else f"{fails} fehlgeschlagen")
    sys.exit(1 if fails else 0)
