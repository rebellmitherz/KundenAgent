"""Tests für Phase F3 — Mandanten-Modell + Register (Multi-Mandanten-Plattform).

Läuft OHNE Engine, ohne Netzwerk, ohne Key.
Aufruf: PYTHONUTF8=1 python product/platform/test_mandant.py
"""
from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.platform.mandant import (
    Mandant,
    MandantenFehler,
    MandantenRegister,
    slugify,
)


# ─── Test-Runner (mit Temp-Verzeichnis) ──────────────────────────────────────

_ok = 0
_fail = 0


def test(name, fn):
    global _ok, _fail
    try:
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
        print(f"  ✓  {name}")
        _ok += 1
    except Exception:
        print(f"  ✗  {name}")
        traceback.print_exc(limit=4)
        _fail += 1


# ─── slugify ──────────────────────────────────────────────────────────────────

def t_slugify(_d):
    assert slugify("Agentur Müller GmbH!") == "agentur_m_ller_gmbh"
    assert slugify("ACME-2026") == "acme-2026"
    assert slugify("   ") == ""


# ─── Mandant ──────────────────────────────────────────────────────────────────

def t_mandant_normalisiert_id(_d):
    m = Mandant(mandant_id="Kunde Eins", name="")
    assert m.mandant_id == "kunde_eins"
    assert m.name == "Kunde Eins"          # Name fällt auf Roh-Eingabe zurück


def t_mandant_leere_id_wirft(_d):
    try:
        Mandant(mandant_id="!!!")
        assert False, "hätte werfen müssen"
    except MandantenFehler:
        pass


def t_mandant_roundtrip(_d):
    m = Mandant(mandant_id="acme", name="ACME", engine_dir="/x/b2bbot",
                standard_zielgruppe="IT-Dienstleister", branche="it")
    m2 = Mandant.from_dict(m.to_dict())
    assert m2 == m


def t_from_dict_ignoriert_fremdfelder(_d):
    m = Mandant.from_dict({"mandant_id": "acme", "name": "ACME", "quatsch": 1})
    assert m.mandant_id == "acme"


# ─── Register: anlegen / holen / isolieren ────────────────────────────────────

def t_anlegen_und_holen(d):
    reg = MandantenRegister(d)
    reg.anlegen(Mandant("acme", name="ACME", engine_dir=str(d / "e1")))
    m = reg.holen("ACME")                  # Lookup über Slug, case-insensitiv
    assert m is not None and m.name == "ACME"
    assert reg.holen("gibt_nicht") is None


def t_data_dir_isoliert(d):
    reg = MandantenRegister(d)
    a = reg.data_dir_fuer("acme")
    b = reg.data_dir_fuer("beta")
    assert a != b
    assert a == d / "mandanten" / "acme"
    reg.anlegen(Mandant("acme", engine_dir=str(d / "e1")))
    assert reg.data_dir_fuer("acme").exists()   # wird beim Anlegen erstellt


def t_doppelte_id_wirft(d):
    reg = MandantenRegister(d)
    reg.anlegen(Mandant("acme", engine_dir=str(d / "e1")))
    try:
        reg.anlegen(Mandant("ACME", engine_dir=str(d / "e2")))
        assert False, "doppelte ID hätte werfen müssen"
    except MandantenFehler:
        pass


def t_geteiltes_engine_dir_wirft(d):
    reg = MandantenRegister(d)
    reg.anlegen(Mandant("acme", engine_dir=str(d / "shared")))
    try:
        reg.anlegen(Mandant("beta", engine_dir=str(d / "shared")))
        assert False, "geteiltes engine_dir hätte werfen müssen"
    except MandantenFehler:
        pass


def t_inaktiver_mandant_blockiert_engine_dir_nicht(d):
    reg = MandantenRegister(d)
    reg.anlegen(Mandant("acme", engine_dir=str(d / "shared"), aktiv=False))
    # inaktiver Mandant gibt die Engine frei → beta darf sie nutzen
    reg.anlegen(Mandant("beta", engine_dir=str(d / "shared")))
    assert reg.holen("beta") is not None


def t_leeres_engine_dir_erlaubt_mehrfach(d):
    reg = MandantenRegister(d)
    reg.anlegen(Mandant("acme"))           # noch nicht eingerichtet
    reg.anlegen(Mandant("beta"))           # auch leer → ok
    assert len(reg.alle()) == 2


# ─── Register: aktualisieren / entfernen / aktive ─────────────────────────────

def t_aktualisieren(d):
    reg = MandantenRegister(d)
    reg.anlegen(Mandant("acme", name="ACME", engine_dir=str(d / "e1")))
    reg.aktualisieren(Mandant("acme", name="ACME AG", engine_dir=str(d / "e1")))
    assert reg.holen("acme").name == "ACME AG"


def t_aktualisieren_unbekannt_wirft(d):
    reg = MandantenRegister(d)
    try:
        reg.aktualisieren(Mandant("ghost"))
        assert False
    except MandantenFehler:
        pass


def t_entfernen(d):
    reg = MandantenRegister(d)
    reg.anlegen(Mandant("acme", engine_dir=str(d / "e1")))
    assert reg.entfernen("ACME") is True
    assert reg.holen("acme") is None
    assert reg.entfernen("acme") is False


def t_nur_aktive(d):
    reg = MandantenRegister(d)
    reg.anlegen(Mandant("a", engine_dir=str(d / "e1")))
    reg.anlegen(Mandant("b", engine_dir=str(d / "e2"), aktiv=False))
    assert len(reg.alle()) == 2
    assert [m.mandant_id for m in reg.alle(nur_aktive=True)] == ["a"]


# ─── Register: Routing + Persistenz ───────────────────────────────────────────

def t_per_owner_routing(d):
    reg = MandantenRegister(d)
    reg.anlegen(Mandant("acme", engine_dir=str(d / "e1"), owner_chat_id="111"))
    reg.anlegen(Mandant("beta", engine_dir=str(d / "e2"), owner_chat_id="222"))
    assert reg.per_owner("222").mandant_id == "beta"
    assert reg.per_owner("999") is None
    assert reg.per_owner("") is None


def t_persistenz_ueber_neustart(d):
    reg = MandantenRegister(d)
    reg.anlegen(Mandant("acme", name="ACME", engine_dir=str(d / "e1"),
                         license_key="LIC-123"))
    # Neue Instanz simuliert Neustart
    reg2 = MandantenRegister(d)
    m = reg2.holen("acme")
    assert m is not None and m.name == "ACME" and m.license_key == "LIC-123"


def t_persistenz_atomar_keine_tmp_reste(d):
    reg = MandantenRegister(d)
    reg.anlegen(Mandant("acme", engine_dir=str(d / "e1")))
    assert (d / "mandanten.json").exists()
    assert not (d / "mandanten.json.tmp").exists()   # tmp wurde umbenannt


if __name__ == "__main__":
    print("\n=== Phase F3 — Mandanten-Modell + Register ===\n")
    print("── slugify / Mandant ──")
    test("slugify", t_slugify)
    test("Mandant normalisiert ID", t_mandant_normalisiert_id)
    test("leere ID → Fehler", t_mandant_leere_id_wirft)
    test("Mandant Roundtrip", t_mandant_roundtrip)
    test("from_dict ignoriert Fremdfelder", t_from_dict_ignoriert_fremdfelder)

    print("\n── Register: anlegen / Isolation ──")
    test("anlegen + holen (Slug-Lookup)", t_anlegen_und_holen)
    test("data_dir je Mandant isoliert", t_data_dir_isoliert)
    test("doppelte ID → Fehler", t_doppelte_id_wirft)
    test("geteiltes engine_dir → Fehler", t_geteiltes_engine_dir_wirft)
    test("inaktiver Mandant gibt engine_dir frei", t_inaktiver_mandant_blockiert_engine_dir_nicht)
    test("leeres engine_dir mehrfach erlaubt", t_leeres_engine_dir_erlaubt_mehrfach)

    print("\n── Register: aktualisieren / entfernen ──")
    test("aktualisieren", t_aktualisieren)
    test("aktualisieren unbekannt → Fehler", t_aktualisieren_unbekannt_wirft)
    test("entfernen", t_entfernen)
    test("nur aktive", t_nur_aktive)

    print("\n── Register: Routing / Persistenz ──")
    test("per_owner Routing", t_per_owner_routing)
    test("Persistenz über Neustart", t_persistenz_ueber_neustart)
    test("atomares Speichern (keine .tmp-Reste)", t_persistenz_atomar_keine_tmp_reste)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
