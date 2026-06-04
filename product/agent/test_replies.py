"""Tests für Phase B.2 — Antworten-Bericht (replies.py) + Runner-Delegation.

Läuft OHNE Engine. Aufruf: PYTHONUTF8=1 python product/agent/test_replies.py
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.agent.replies import antworten_bericht, termine
from product.agent.runner import AgentRunner


def _antwort(firma, termin=False, grund="", klasse="", sentiment=""):
    return {"firma": firma, "betreff": "AW", "auszug": "...", "klasse": klasse,
            "sentiment": sentiment, "terminwunsch": termin, "termin_grund": grund,
            "kategorie": "", "entry_key": firma}


# ─── Mock-Bridge für Runner-Delegation ──────────────────────────────────────


class MockBridge:
    def __init__(self, antworten):
        self._a = antworten
        self.aufrufe = 0

    def antworten_lesen(self, limit=30):
        self.aufrufe += 1
        return self._a[:limit]


# ─── Runner ──────────────────────────────────────────────────────────────────

_ok = 0
_fail = 0


def test(name, fn):
    global _ok, _fail
    try:
        fn()
        print(f"  ✓  {name}")
        _ok += 1
    except Exception:
        print(f"  ✗  {name}")
        traceback.print_exc(limit=4)
        _fail += 1


# ─── Bericht ─────────────────────────────────────────────────────────────────

def t_leer():
    t = antworten_bericht([])
    assert "Noch keine Antworten" in t


def t_termin_hervorgehoben():
    a = [_antwort("Müller Bau", termin=True, grund="Termin nächste Woche"),
         _antwort("Schmidt GmbH", klasse="not_interested")]
    t = antworten_bericht(a)
    assert "Termin-Signal" in t
    assert "Müller Bau" in t
    assert "Termin nächste Woche" in t
    assert "👉" in t   # Handlungsaufruf bei Termin


def t_nur_positive_ohne_termin():
    a = [_antwort("A GmbH", klasse="interested"), _antwort("B GmbH", sentiment="positiv")]
    t = antworten_bericht(a)
    assert "neue antwort" in t.lower()
    assert "👍" in t
    assert "Termin-Signal" not in t


def t_rest_zaehlung():
    a = [_antwort("T1", termin=True, grund="g")]
    a += [_antwort(f"N{i}", klasse="neutral") for i in range(8)]
    t = antworten_bericht(a)
    assert "weitere" in t


def t_termine_filter():
    a = [_antwort("A", termin=True), _antwort("B"), _antwort("C", termin=True)]
    nur = termine(a)
    assert [x["firma"] for x in nur] == ["A", "C"]


# ─── Runner-Delegation ───────────────────────────────────────────────────────

def t_runner_antworten_delegiert():
    bridge = MockBridge([_antwort("X", termin=True, grund="g")])
    runner = AgentRunner(bridge, data_dir=".")  # data_dir egal hier
    res = runner.antworten()
    assert len(res) == 1 and bridge.aufrufe == 1
    assert "Termin-Signal" in runner.antworten_bericht()
    assert len(runner.termin_signale()) == 1


def t_runner_ohne_bridge_leer():
    runner = AgentRunner(None, data_dir=".")
    assert runner.antworten() == []
    assert "Noch keine Antworten" in runner.antworten_bericht()
    assert runner.termin_signale() == []


if __name__ == "__main__":
    print("\n=== Phase B.2 — Antworten-Bericht + Runner ===\n")
    test("leer → freundlicher Hinweis", t_leer)
    test("Terminwunsch hervorgehoben", t_termin_hervorgehoben)
    test("nur positive ohne Termin", t_nur_positive_ohne_termin)
    test("Rest-Zählung", t_rest_zaehlung)
    test("termine()-Filter", t_termine_filter)
    test("Runner delegiert an Bridge", t_runner_antworten_delegiert)
    test("Runner ohne Bridge → leer", t_runner_ohne_bridge_leer)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
