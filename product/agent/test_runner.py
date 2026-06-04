"""Tests für Phase A.5 — Agent-Runner (runner.py), die geteilte Anbindung.

Läuft OHNE API-Key, OHNE echte Engine. Temp-Verzeichnis statt data/.
Aufruf: PYTHONUTF8=1 python product/agent/test_runner.py

Abgedeckte Szenarien:
  - starten(): Lauf läuft, persistiert, erreicht Mensch-Tor bei Ziel
  - starten(): Lücke→Auffüllung→Erschöpfung→ehrlich Aufgeben, persistiert
  - laeufe()/lauf(): lesen nach Lauf, unbekannt → None
  - mehrere Läufe isoliert
  - ohne Key + ohne Reporter lauffähig (deterministischer Kern)
  - kein Sende-Pfad: Agent sendet nie selbst (kein Sende-Werkzeug im Verlauf)
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

from product.agent.brain import Aktionstyp
from product.agent.runner import AgentRunner
from product.agent.tools import SENDE_WERKZEUGE_GESPERRT
from product.operator.order_schema import Auftrag


# ─── Mocks ───────────────────────────────────────────────────────────────────


@dataclass
class MockBrueckenErgebnis:
    ok: bool
    leads_gefunden: int = 0
    leads_sauber: int = 0
    meldung: str = ""
    rohdaten: dict = field(default_factory=dict)


class SimulierteEngine:
    def __init__(self, plan=None, start: int = 0):
        self.sendbar = start
        self._plan = list(plan or [])
        self._i = 0

    def status_lesen(self) -> dict:
        return {"pipeline_total": self.sendbar, "sendable": self.sendbar,
                "approved": 0, "sent_total": 0, "already_contacted": 0}

    def suchen(self, auftrag: Auftrag) -> MockBrueckenErgebnis:
        auftrag.starten()
        z = self._plan[self._i] if self._i < len(self._plan) else 0
        self._i += 1
        self.sendbar += z
        return MockBrueckenErgebnis(ok=True, leads_gefunden=z, leads_sauber=z)


def _auftrag(zielgruppe="Handwerker", region="NRW", anzahl=100) -> Auftrag:
    a = Auftrag(zielgruppe=zielgruppe, region=region, lead_anzahl=anzahl, angebot="ERP")
    a.bestaetigen()
    return a


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

def t_starten_ziel_erreicht_mensch_tor(d):
    runner = AgentRunner(SimulierteEngine(plan=[30], start=0), data_dir=d)
    erg = runner.starten(_auftrag(anzahl=25))
    assert erg.menschliches_tor
    assert erg.abschluss.typ == Aktionstyp.MENSCH_FRAGEN
    assert erg.lage.sendbar >= 25


def t_starten_persistiert(d):
    a = _auftrag(anzahl=25)
    runner = AgentRunner(SimulierteEngine(plan=[30], start=0), data_dir=d)
    runner.starten(a)
    rec = runner.lauf(a.auftrags_id)
    assert rec is not None
    assert rec["status"] == "wartet_auf_mensch"
    assert len(rec["schritte"]) >= 1


def t_starten_luecke_erschoepft_aufgeben(d):
    a = _auftrag(anzahl=1000)
    runner = AgentRunner(SimulierteEngine(plan=[20], start=0), data_dir=d)
    erg = runner.starten(a)
    assert erg.abschluss.typ == Aktionstyp.AUFGEBEN
    rec = runner.lauf(a.auftrags_id)
    assert rec["status"] == "aufgegeben"
    assert "ausgeschöpft" in erg.abschluss.begruendung


def t_laeufe_listet_nach_start(d):
    runner = AgentRunner(SimulierteEngine(plan=[30], start=0), data_dir=d)
    assert runner.laeufe() == []
    a = _auftrag(anzahl=25)
    runner.starten(a)
    laeufe = runner.laeufe()
    assert len(laeufe) == 1
    assert laeufe[0]["auftrags_id"] == a.auftrags_id
    assert laeufe[0]["funnel"]["ziel_erreicht"] is True


def t_lauf_unbekannt_none(d):
    runner = AgentRunner(SimulierteEngine(), data_dir=d)
    assert runner.lauf("gibt_es_nicht") is None


def t_mehrere_laeufe_isoliert(d):
    runner = AgentRunner(SimulierteEngine(plan=[30, 30, 30, 30], start=0), data_dir=d)
    a = _auftrag("Handwerker", "NRW", anzahl=10)
    b = _auftrag("Coaches", "Berlin", anzahl=10)
    runner.starten(a)
    runner.starten(b)
    assert len(runner.laeufe()) == 2
    assert runner.lauf(a.auftrags_id)["auftrag"]["zielgruppe"] == "Handwerker"
    assert runner.lauf(b.auftrags_id)["auftrag"]["zielgruppe"] == "Coaches"


def t_ohne_key_ohne_reporter_laeuft(d):
    """Kein api_key, kein Reporter → deterministischer Kern, kein Crash."""
    runner = AgentRunner(SimulierteEngine(plan=[30], start=0), data_dir=d,
                         reporter=None, api_key=None)
    erg = runner.starten(_auftrag(anzahl=25))
    assert erg.erfolgreich


def t_kein_sende_werkzeug_im_verlauf(d):
    """Sicherheit: kein Sende-Werkzeug taucht je im persistierten Verlauf auf."""
    a = _auftrag(anzahl=1000)
    runner = AgentRunner(SimulierteEngine(plan=[20], start=0), data_dir=d)
    runner.starten(a)
    rec = runner.lauf(a.auftrags_id)
    benutzte = {s["werkzeug"] for s in rec["schritte"]}
    assert not (benutzte & SENDE_WERKZEUGE_GESPERRT), f"Sende-Werkzeug benutzt: {benutzte}"


# ─── Haupt-Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n=== Phase A.5 — Agent-Runner (runner.py) ===\n")
    test("starten → Ziel → Mensch-Tor", t_starten_ziel_erreicht_mensch_tor)
    test("starten persistiert den Lauf", t_starten_persistiert)
    test("Lücke → Erschöpfung → Aufgeben (persistiert)", t_starten_luecke_erschoepft_aufgeben)
    test("laeufe() listet nach Start", t_laeufe_listet_nach_start)
    test("lauf(unbekannt) → None", t_lauf_unbekannt_none)
    test("mehrere Läufe isoliert", t_mehrere_laeufe_isoliert)
    test("ohne Key + ohne Reporter lauffähig", t_ohne_key_ohne_reporter_laeuft)
    test("kein Sende-Werkzeug im Verlauf", t_kein_sende_werkzeug_im_verlauf)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
