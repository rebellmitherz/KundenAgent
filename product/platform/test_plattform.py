"""Tests für Phase F4 — Plattform-Orchestrierung (Runner/Bridge je Mandant).

Läuft OHNE echte Engine: bridge_factory wird gemockt.
Aufruf: PYTHONUTF8=1 python product/platform/test_plattform.py
"""
from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.bridge.engine_bridge import EngineError
from product.platform.mandant import Mandant, MandantenFehler, MandantenRegister
from product.platform.plattform import Plattform, PlattformWatcher


# ─── Mock-Bridge (verhält sich wie EngineBridge für den Runner) ───────────────


class MockBridge:
    """Minimaler Bridge-Ersatz. Merkt sich engine_dir, liefert ein Termin-Signal."""

    def __init__(self, engine_dir, antworten=None):
        self.engine_dir = engine_dir
        self._antworten = antworten or []

    def antworten_lesen(self, limit=30):
        return list(self._antworten)[:limit]

    def status_lesen(self):
        return {"pipeline_total": 0, "sendable": 0, "sent_total": 0}

    def kampagne_rohdaten(self, campaign=None, limit=1000):
        return {"entries": [], "antwort_keys": [], "termin_keys": []}

    def followups_faellig(self, limit=50):
        return []

    def antworten_abrufen(self, limit=30):
        from product.bridge.engine_bridge import EngineBrueckenErgebnis
        return EngineBrueckenErgebnis(ok=True, meldung="ok")


def _bridge_factory(antworten_je_dir=None):
    antworten_je_dir = antworten_je_dir or {}
    return lambda ed: MockBridge(ed, antworten_je_dir.get(ed, []))


def _termin_antwort(firma="Echt GmbH", ek="k1"):
    # echter Termin: terminwunsch + sauberer Text (besteht F1-Triage)
    return {"firma": firma, "entry_key": ek, "terminwunsch": True,
            "termin_grund": "möchte Gespräch", "betreff": "AW",
            "auszug": "Sehr gerne, schlagen Sie einen Termin vor."}


# ─── Test-Runner ─────────────────────────────────────────────────────────────

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


def _register(d, *mandanten) -> MandantenRegister:
    reg = MandantenRegister(d)
    for m in mandanten:
        reg.anlegen(m)
    return reg


# ─── runner_fuer / Isolation ──────────────────────────────────────────────────

def t_runner_isolierte_data_dirs(d):
    reg = _register(d,
                    Mandant("acme", engine_dir=str(d / "e_acme")),
                    Mandant("beta", engine_dir=str(d / "e_beta")))
    p = Plattform(reg, bridge_factory=_bridge_factory(), reporter_factory=lambda ed: None)
    r_acme = p.runner_fuer("acme")
    r_beta = p.runner_fuer("beta")
    # Verschiedene, isolierte Daten-Verzeichnisse
    assert r_acme.speicher._dir != r_beta.speicher._dir
    assert "acme" in str(r_acme.speicher._dir)
    assert "beta" in str(r_beta.speicher._dir)


def t_runner_gecacht(d):
    reg = _register(d, Mandant("acme", engine_dir=str(d / "e1")))
    p = Plattform(reg, bridge_factory=_bridge_factory(), reporter_factory=lambda ed: None)
    assert p.runner_fuer("acme") is p.runner_fuer("ACME")   # gleiches Objekt, Slug-Lookup


def t_runner_unbekannt_wirft(d):
    p = Plattform(_register(d), bridge_factory=_bridge_factory())
    try:
        p.runner_fuer("ghost")
        assert False
    except MandantenFehler:
        pass


def t_runner_ohne_engine_wirft(d):
    reg = _register(d, Mandant("acme"))   # kein engine_dir
    p = Plattform(reg, bridge_factory=_bridge_factory())
    try:
        p.runner_fuer("acme")
        assert False
    except EngineError:
        pass


def t_runner_oder_none(d):
    reg = _register(d, Mandant("acme"))   # nicht eingerichtet
    p = Plattform(reg, bridge_factory=_bridge_factory())
    assert p.runner_oder_none("acme") is None
    assert p.betriebsbereit("acme") is False


def t_bridge_factory_bekommt_engine_dir(d):
    gesehen = {}
    reg = _register(d, Mandant("acme", engine_dir=str(d / "e_acme")))
    def factory(ed):
        gesehen["ed"] = ed
        return MockBridge(ed)
    p = Plattform(reg, bridge_factory=factory, reporter_factory=lambda ed: None)
    p.runner_fuer("acme")
    assert gesehen["ed"] == str(d / "e_acme")


def t_api_key_default_und_override(d):
    reg = _register(d,
                    Mandant("acme", engine_dir=str(d / "e1")),
                    Mandant("beta", engine_dir=str(d / "e2"), anthropic_api_key="sk-beta"))
    p = Plattform(reg, api_key_default="sk-default",
                  bridge_factory=_bridge_factory(), reporter_factory=lambda ed: None)
    assert p.runner_fuer("acme")._api_key == "sk-default"
    assert p.runner_fuer("beta")._api_key == "sk-beta"


# ─── Routing ──────────────────────────────────────────────────────────────────

def t_routing_per_chat(d):
    reg = _register(d,
                    Mandant("acme", engine_dir=str(d / "e1"), owner_chat_id="111"),
                    Mandant("beta", engine_dir=str(d / "e2"), owner_chat_id="222"))
    p = Plattform(reg, bridge_factory=_bridge_factory())
    assert p.mandant_fuer_chat("222").mandant_id == "beta"
    assert p.mandant_fuer_chat("999") is None


# ─── aktive_runner ────────────────────────────────────────────────────────────

def t_aktive_runner_ueberspringt_nicht_eingerichtete(d):
    reg = _register(d,
                    Mandant("acme", engine_dir=str(d / "e1")),   # ok
                    Mandant("beta"),                              # keine Engine
                    Mandant("gamma", engine_dir=str(d / "e3"), aktiv=False))  # inaktiv
    p = Plattform(reg, bridge_factory=_bridge_factory(), reporter_factory=lambda ed: None)
    ids = {m.mandant_id for m, _ in p.aktive_runner()}
    assert ids == {"acme"}   # beta nicht eingerichtet, gamma inaktiv


# ─── PlattformWatcher: getrennte Ziel-Chats ──────────────────────────────────

def t_watcher_meldet_je_mandant_an_eigenen_chat(d):
    ed_a, ed_b = str(d / "e1"), str(d / "e2")
    reg = _register(d,
                    Mandant("acme", engine_dir=ed_a, owner_chat_id="111"),
                    Mandant("beta", engine_dir=ed_b, owner_chat_id="222"))
    # Nur acme hat einen Termin
    bf = _bridge_factory({ed_a: [_termin_antwort("Acme-Lead")]})
    p = Plattform(reg, bridge_factory=bf, reporter_factory=lambda ed: None)

    gesendet = []   # (chat_id, text)
    pw = PlattformWatcher(p, lambda cid, txt: gesendet.append((cid, txt)),
                          auto_abruf=False)
    pw.jetzt_pruefen()

    ziele = {cid for cid, _ in gesendet}
    assert ziele == {"111"}                       # nur acmes Chat
    assert any("Acme-Lead" in t for _, t in gesendet)
    assert all(cid != "222" for cid, _ in gesendet)   # kein Querverkehr zu beta


def t_watcher_ohne_owner_chat_kein_watcher(d):
    reg = _register(d, Mandant("acme", engine_dir=str(d / "e1")))  # kein owner_chat_id
    p = Plattform(reg, bridge_factory=_bridge_factory(), reporter_factory=lambda ed: None)
    pw = PlattformWatcher(p, lambda c, t: None, auto_abruf=False)
    pw.jetzt_pruefen()
    assert pw.watcher == {}


def t_watcher_deaktivierter_mandant_wird_entfernt(d):
    reg = _register(d, Mandant("acme", engine_dir=str(d / "e1"), owner_chat_id="111"))
    p = Plattform(reg, bridge_factory=_bridge_factory(), reporter_factory=lambda ed: None)
    pw = PlattformWatcher(p, lambda c, t: None, auto_abruf=False)
    pw.jetzt_pruefen()
    assert "acme" in pw.watcher
    # Mandant deaktivieren → Watcher verschwindet beim nächsten Aufbau
    reg.aktualisieren(Mandant("acme", engine_dir=str(d / "e1"),
                              owner_chat_id="111", aktiv=False))
    p.invalidieren("acme")
    pw.jetzt_pruefen()
    assert "acme" not in pw.watcher


if __name__ == "__main__":
    print("\n=== Phase F4 — Plattform-Orchestrierung ===\n")
    print("── runner_fuer / Isolation ──")
    test("isolierte data_dirs je Mandant", t_runner_isolierte_data_dirs)
    test("Runner gecacht (Slug-Lookup)", t_runner_gecacht)
    test("unbekannter Mandant → Fehler", t_runner_unbekannt_wirft)
    test("ohne Engine → EngineError", t_runner_ohne_engine_wirft)
    test("runner_oder_none / betriebsbereit", t_runner_oder_none)
    test("bridge_factory bekommt engine_dir", t_bridge_factory_bekommt_engine_dir)
    test("api_key default + override", t_api_key_default_und_override)

    print("\n── Routing ──")
    test("Routing per Chat-ID", t_routing_per_chat)

    print("\n── aktive_runner ──")
    test("überspringt nicht eingerichtete/inaktive", t_aktive_runner_ueberspringt_nicht_eingerichtete)

    print("\n── PlattformWatcher ──")
    test("meldet je Mandant an eigenen Chat (kein Querverkehr)", t_watcher_meldet_je_mandant_an_eigenen_chat)
    test("ohne owner_chat_id → kein Watcher", t_watcher_ohne_owner_chat_kein_watcher)
    test("deaktivierter Mandant → Watcher entfernt", t_watcher_deaktivierter_mandant_wird_entfernt)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
