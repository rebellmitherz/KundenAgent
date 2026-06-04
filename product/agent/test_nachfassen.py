"""Tests für Phase B.3 — Runner-Nachfassen (human-gated) + Memory.

Läuft OHNE echte Engine: Bridge gemockt, KEIN Versand.
Aufruf: PYTHONUTF8=1 python product/agent/test_nachfassen.py
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


@dataclass
class MockErg:
    ok: bool
    leads_gefunden: int = 0
    leads_sauber: int = 0
    meldung: str = ""
    rohdaten: dict = field(default_factory=dict)


class SimEngine:
    """Such-Engine + protokollierende Freigabe/Followup (kein echter Versand)."""

    def __init__(self, plan=None, start=0, followup_ok=True, nachgefasst=0, faellig=None):
        self.sendbar = start
        self._plan = list(plan or [])
        self._i = 0
        self.followup_aufrufe = []
        self.freigabe_aufrufe = []
        self._fok = followup_ok
        self._nach = nachgefasst
        self._faellig = faellig or []

    def status_lesen(self):
        return {"sendable": self.sendbar, "pipeline_total": self.sendbar, "sent_total": 0}

    def suchen(self, auftrag):
        auftrag.starten()
        z = self._plan[self._i] if self._i < len(self._plan) else 0
        self._i += 1
        self.sendbar += z
        return MockErg(ok=True, leads_gefunden=z, leads_sauber=z)

    def freigabe_ausfuehren(self, limit=20, *, bestaetigt=False):
        self.freigabe_aufrufe.append((limit, bestaetigt))
        return MockErg(ok=True, leads_sauber=limit)

    def followup_ausfuehren(self, limit=20, *, bestaetigt=False):
        self.followup_aufrufe.append((limit, bestaetigt))
        if not self._fok:
            return MockErg(ok=False, meldung="Nachfassen fehlgeschlagen")
        return MockErg(ok=True, leads_sauber=self._nach, meldung=f"Nachgefasst: {self._nach}")

    def followups_faellig(self, limit=50):
        return self._faellig[:limit]


def _auftrag(anzahl=25):
    a = Auftrag(zielgruppe="Handwerker", region="NRW", lead_anzahl=anzahl, angebot="Web")
    a.bestaetigen()
    return a


def _runner_gesendet(d, engine):
    """Runner, dessen Lauf bereits gesendet wurde (Status 'gesendet')."""
    a = _auftrag(25)
    runner = AgentRunner(engine, data_dir=d)
    erg = runner.starten(a)
    assert erg.menschliches_tor
    res = runner.freigeben(a.auftrags_id, bestaetigt=True)
    assert res["ok"] and runner.lauf(a.auftrags_id)["status"] == "gesendet"
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


# ─── Fällig-Vorschau ─────────────────────────────────────────────────────────

def t_faellig_delegiert(d):
    engine = SimEngine(faellig=[{"firma": "A"}, {"firma": "B"}])
    runner = AgentRunner(engine, data_dir=d)
    assert len(runner.nachfass_faellig()) == 2


def t_faellig_ohne_bridge(d):
    runner = AgentRunner(None, data_dir=d)
    assert runner.nachfass_faellig() == []


# ─── Nachfass-Versand (gated) ────────────────────────────────────────────────

def t_ohne_bestaetigung_abgelehnt(d):
    engine = SimEngine(plan=[30])
    runner, a = _runner_gesendet(d, engine)
    res = runner.nachfassen(a.auftrags_id, limit=10)   # keine Bestätigung
    assert not res["ok"]
    assert engine.followup_aufrufe == [], "Bridge trotz fehlender Bestätigung gerufen!"


def t_unbekannter_lauf_abgelehnt(d):
    engine = SimEngine()
    runner = AgentRunner(engine, data_dir=d)
    res = runner.nachfassen("gibt_es_nicht", bestaetigt=True)
    assert not res["ok"]
    assert engine.followup_aufrufe == []


def t_nicht_gesendet_abgelehnt(d):
    """Lauf am Tor (wartet_auf_mensch), noch nicht gesendet → kein Nachfassen."""
    engine = SimEngine(plan=[30])
    a = _auftrag(25)
    runner = AgentRunner(engine, data_dir=d)
    runner.starten(a)   # Status: wartet_auf_mensch
    res = runner.nachfassen(a.auftrags_id, bestaetigt=True)
    assert not res["ok"]
    assert "nicht nachfass-bereit" in res["meldung"]
    assert engine.followup_aufrufe == []


def t_gesendet_bestaetigt_fasst_nach(d):
    engine = SimEngine(plan=[30], nachgefasst=12)
    runner, a = _runner_gesendet(d, engine)
    res = runner.nachfassen(a.auftrags_id, limit=15, bestaetigt=True)
    assert res["ok"]
    assert res["nachgefasst"] == 12
    assert engine.followup_aufrufe == [(15, True)]
    rec = runner.lauf(a.auftrags_id)
    assert rec["status"] == "nachgefasst"
    assert len(rec["nachfass"]) == 1
    assert rec["nachfass"][0]["nachgefasst"] == 12


def t_nachfass_fehler_status_bleibt(d):
    engine = SimEngine(plan=[30], followup_ok=False)
    runner, a = _runner_gesendet(d, engine)
    res = runner.nachfassen(a.auftrags_id, bestaetigt=True)
    assert not res["ok"]
    rec = runner.lauf(a.auftrags_id)
    assert rec["status"] == "gesendet", "Fehlversuch wurde als nachgefasst markiert!"
    assert rec["nachfass"][0]["ok"] is False


def t_memory_nachfass_unbekannt_false(d):
    sp = LaufSpeicher(d)
    assert sp.nachfass_aufzeichnen("gibt_es_nicht", nachgefasst=1, meldung="x", ok=True) is False


if __name__ == "__main__":
    print("\n=== Phase B.3 — Runner-Nachfassen (human-gated) ===\n")
    test("Fällig-Vorschau delegiert", t_faellig_delegiert)
    test("Fällig ohne Bridge → leer", t_faellig_ohne_bridge)
    test("ohne Bestätigung → abgelehnt", t_ohne_bestaetigung_abgelehnt)
    test("unbekannter Lauf → abgelehnt", t_unbekannter_lauf_abgelehnt)
    test("nicht gesendet → abgelehnt", t_nicht_gesendet_abgelehnt)
    test("gesendet + bestätigt → fasst nach + Memory", t_gesendet_bestaetigt_fasst_nach)
    test("Nachfass-Fehler → Status bleibt 'gesendet'", t_nachfass_fehler_status_bleibt)
    test("memory: unbekannter Lauf → False", t_memory_nachfass_unbekannt_false)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
