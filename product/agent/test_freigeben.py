"""Tests für Phase B.1 — Runner-Freigabe (human-gated Send) + Memory.

Läuft OHNE echte Engine: die Bridge-Freigabe wird gemockt, es wird NIE gesendet.
Aufruf: PYTHONUTF8=1 python product/agent/test_freigeben.py

Kernaussagen:
  - ohne bestaetigt=True → abgelehnt, Bridge NICHT aufgerufen
  - unbekannter Lauf / falscher Status → abgelehnt, Bridge NICHT aufgerufen
  - am Tor (wartet_auf_mensch) + bestaetigt → Bridge gerufen, Memory: Status
    'gesendet', Freigabe protokolliert
  - Doppel-Freigabe nach Versand → abgelehnt (Status nicht mehr am Tor)
  - Bridge-Fehler → ok=False, Status NICHT fälschlich 'gesendet'
  - memory.freigabe_aufzeichnen: unbekannter Lauf → False
"""
from __future__ import annotations

import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.agent.memory import LaufSpeicher
from product.agent.runner import AgentRunner
from product.operator.order_schema import Auftrag


# ─── Mocks ───────────────────────────────────────────────────────────────────


@dataclass
class MockBrueckenErgebnis:
    ok: bool
    leads_gefunden: int = 0
    leads_sauber: int = 0
    meldung: str = ""
    rohdaten: dict = field(default_factory=dict)


class SimEngine:
    """Such-Engine + protokollierende Freigabe (kein echter Versand)."""

    def __init__(self, plan=None, start=0, freigabe_ok=True, gesendet=0):
        self.sendbar = start
        self._plan = list(plan or [])
        self._i = 0
        self.freigabe_aufrufe = []   # list[(limit, bestaetigt)]
        self._freigabe_ok = freigabe_ok
        self._gesendet = gesendet

    def status_lesen(self):
        return {"sendable": self.sendbar, "pipeline_total": self.sendbar, "sent_total": 0}

    def suchen(self, auftrag):
        auftrag.starten()
        z = self._plan[self._i] if self._i < len(self._plan) else 0
        self._i += 1
        self.sendbar += z
        return MockBrueckenErgebnis(ok=True, leads_gefunden=z, leads_sauber=z)

    def freigabe_ausfuehren(self, limit=20, *, bestaetigt=False):
        self.freigabe_aufrufe.append((limit, bestaetigt))
        if not self._freigabe_ok:
            return MockBrueckenErgebnis(ok=False, meldung="Send fehlgeschlagen")
        return MockBrueckenErgebnis(ok=True, leads_sauber=self._gesendet,
                                    meldung=f"Gesendet: {self._gesendet}")


def _auftrag(anzahl=25):
    a = Auftrag(zielgruppe="Handwerker", region="NRW", lead_anzahl=anzahl, angebot="Websites")
    a.bestaetigen()
    return a


def _runner_am_tor(d, engine):
    """Baut einen Runner, dessen Lauf am harten Tor steht (wartet_auf_mensch)."""
    a = _auftrag(anzahl=25)
    runner = AgentRunner(engine, data_dir=d)
    erg = runner.starten(a)
    assert erg.menschliches_tor   # Vorbedingung
    return runner, a


# ─── Runner ──────────────────────────────────────────────────────────────────

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


# ─── Tests ───────────────────────────────────────────────────────────────────

def t_ohne_bestaetigung_abgelehnt(d):
    engine = SimEngine(plan=[30])
    runner, a = _runner_am_tor(d, engine)
    res = runner.freigeben(a.auftrags_id, limit=10)   # bestaetigt fehlt
    assert not res["ok"]
    assert engine.freigabe_aufrufe == [], "Bridge wurde trotz fehlender Bestätigung gerufen!"


def t_unbekannter_lauf_abgelehnt(d):
    engine = SimEngine()
    runner = AgentRunner(engine, data_dir=d)
    res = runner.freigeben("gibt_es_nicht", bestaetigt=True)
    assert not res["ok"]
    assert engine.freigabe_aufrufe == []


def t_falscher_status_abgelehnt(d):
    """Lauf, der nicht am Tor steht (aufgegeben), darf nicht senden."""
    engine = SimEngine(plan=[20])   # Ziel 1000 → erschöpft → aufgegeben
    a = _auftrag(anzahl=1000)
    runner = AgentRunner(engine, data_dir=d)
    erg = runner.starten(a)
    assert not erg.menschliches_tor
    res = runner.freigeben(a.auftrags_id, bestaetigt=True)
    assert not res["ok"]
    assert "nicht freigabebereit" in res["meldung"]
    assert engine.freigabe_aufrufe == []


def t_am_tor_bestaetigt_sendet(d):
    engine = SimEngine(plan=[30], gesendet=25)
    runner, a = _runner_am_tor(d, engine)
    res = runner.freigeben(a.auftrags_id, limit=20, bestaetigt=True)
    assert res["ok"]
    assert res["gesendet"] == 25
    # Bridge mit bestaetigt=True gerufen
    assert engine.freigabe_aufrufe == [(20, True)]
    # Memory: Status gesendet + Freigabe protokolliert
    rec = runner.lauf(a.auftrags_id)
    assert rec["status"] == "gesendet"
    assert len(rec["freigaben"]) == 1
    assert rec["freigaben"][0]["gesendet"] == 25
    assert rec["freigaben"][0]["ok"] is True


def t_doppel_freigabe_abgelehnt(d):
    engine = SimEngine(plan=[30], gesendet=25)
    runner, a = _runner_am_tor(d, engine)
    erst = runner.freigeben(a.auftrags_id, bestaetigt=True)
    assert erst["ok"]
    # Zweiter Versuch: Status ist jetzt 'gesendet', nicht mehr am Tor
    zweit = runner.freigeben(a.auftrags_id, bestaetigt=True)
    assert not zweit["ok"]
    assert len(engine.freigabe_aufrufe) == 1, "Doppel-Versand passierte!"


def t_bridge_fehler_status_nicht_gesendet(d):
    engine = SimEngine(plan=[30], freigabe_ok=False)
    runner, a = _runner_am_tor(d, engine)
    res = runner.freigeben(a.auftrags_id, bestaetigt=True)
    assert not res["ok"]
    rec = runner.lauf(a.auftrags_id)
    assert rec["status"] == "wartet_auf_mensch", "Fehlversand wurde als gesendet markiert!"
    # Fehlversuch ist trotzdem protokolliert (ok=False)
    assert rec["freigaben"][0]["ok"] is False


def t_memory_freigabe_unbekannt_false(d):
    sp = LaufSpeicher(d)
    assert sp.freigabe_aufzeichnen("gibt_es_nicht", gesendet=1, meldung="x", ok=True) is False


# ─── Haupt-Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n=== Phase B.1 — Runner-Freigabe (human-gated) ===\n")
    test("ohne Bestätigung → abgelehnt, keine Bridge", t_ohne_bestaetigung_abgelehnt)
    test("unbekannter Lauf → abgelehnt", t_unbekannter_lauf_abgelehnt)
    test("falscher Status → abgelehnt", t_falscher_status_abgelehnt)
    test("am Tor + bestätigt → sendet + Memory", t_am_tor_bestaetigt_sendet)
    test("Doppel-Freigabe → abgelehnt", t_doppel_freigabe_abgelehnt)
    test("Bridge-Fehler → Status bleibt am Tor", t_bridge_fehler_status_nicht_gesendet)
    test("memory: unbekannter Lauf → False", t_memory_freigabe_unbekannt_false)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
