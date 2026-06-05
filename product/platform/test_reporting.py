"""Tests für Phase F5 — Revenue-Reporting pro Mandant + Gesamtsicht.

Läuft OHNE echte Engine.
Aufruf: PYTHONUTF8=1 python product/platform/test_reporting.py
"""
from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.platform.mandant import Mandant, MandantenRegister
from product.platform.plattform import Plattform
from product.platform.reporting import (
    mandant_report,
    mandant_report_text,
    plattform_report,
    plattform_report_text,
)

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


# ─── Mock-Runner ──────────────────────────────────────────────────────────────


class MockRunner:
    def __init__(self, termine=0, pruefen=0, antworten=0, funnel_stufen=None,
                 ob=0, tob=0):
        self._t = termine
        self._p = pruefen
        self._a = antworten
        self._ob = ob
        self._tob = tob
        self._stufen = funnel_stufen or {}

    def termin_signale(self, limit=30): return [{}] * self._t
    def pruef_termine(self, limit=30): return [{}] * self._p
    def antworten(self, limit=30): return [{}] * self._a
    def funnel(self, campaign=None):
        return {"stufen": self._stufen, "antwort_ohne_bezug": self._ob,
                "termin_ohne_bezug": self._tob}


def _plattform(d, mandanten_runner: dict):
    """Baut eine Plattform mit Mock-Runnern je Mandant."""
    reg = MandantenRegister(d)
    runner_map = {}
    for mid, runner in mandanten_runner.items():
        m = Mandant(mid, engine_dir=str(d / f"e_{mid}"), owner_chat_id=mid)
        reg.anlegen(m)
        runner_map[m.mandant_id] = runner

    def bridge_factory(ed):
        return None  # irrelevant — runner direkt injiziert

    p = Plattform(reg, bridge_factory=bridge_factory,
                  reporter_factory=lambda ed: None)
    # Runner direkt ins Cache schreiben (Dependency Injection)
    for mid, r in runner_map.items():
        p._runners[mid] = r
    return p


# ─── mandant_report ───────────────────────────────────────────────────────────

def t_report_betriebsbereit(d):
    p = _plattform(d, {"acme": MockRunner(termine=2, pruefen=1, antworten=5,
                                           funnel_stufen={"angeschrieben": 10})})
    r = mandant_report("acme", p)
    assert r["betriebsbereit"] is True
    assert r["termine_bestaetigt"] == 2
    assert r["termine_pruefen"] == 1
    assert r["antworten_gesamt"] == 5
    assert r["funnel"]["angeschrieben"] == 10
    assert r["error"] == ""


def t_report_nicht_eingerichtet(d):
    reg = MandantenRegister(d)
    reg.anlegen(Mandant("ghost"))          # kein engine_dir
    p = Plattform(reg, bridge_factory=lambda ed: None)
    r = mandant_report("ghost", p)
    assert r["betriebsbereit"] is False
    assert r["termine_bestaetigt"] == 0


def t_report_text_zeigt_termine(d):
    p = _plattform(d, {"acme": MockRunner(termine=3, antworten=7)})
    r = mandant_report("acme", p)
    t = mandant_report_text(r, name="ACME GmbH")
    assert "3 bestätigte" in t
    assert "ACME GmbH" in t


def t_report_text_zeigt_pruefen(d):
    p = _plattform(d, {"acme": MockRunner(pruefen=2)})
    r = mandant_report("acme", p)
    t = mandant_report_text(r)
    assert "Prüfung" in t


def t_report_text_ohne_bezug(d):
    p = _plattform(d, {"acme": MockRunner(ob=4, tob=1)})
    r = mandant_report("acme", p)
    t = mandant_report_text(r)
    assert "4 Antwort" in t and "früherer Kampagne" in t
    assert "1 mit Termin-Signal" in t


def t_report_text_keine_aktivitaet(d):
    p = _plattform(d, {"acme": MockRunner()})
    r = mandant_report("acme", p)
    t = mandant_report_text(r)
    assert "Noch keine Aktivität" in t


def t_report_nicht_eingerichtet_text(d):
    reg = MandantenRegister(d)
    reg.anlegen(Mandant("ghost"))
    p = Plattform(reg, bridge_factory=lambda ed: None)
    r = mandant_report("ghost", p)
    t = mandant_report_text(r)
    assert "nicht eingerichtet" in t


# ─── plattform_report / Gesamtsicht ───────────────────────────────────────────

def t_gesamtsicht_alle_mandanten(d):
    p = _plattform(d, {
        "acme": MockRunner(termine=2),
        "beta": MockRunner(termine=0, antworten=3),
    })
    berichte = plattform_report(p)
    assert len(berichte) == 2
    ids = {r["mandant_id"] for r in berichte}
    assert ids == {"acme", "beta"}


def t_gesamtsicht_text_summiert(d):
    p = _plattform(d, {
        "acme": MockRunner(termine=2, antworten=5),
        "beta": MockRunner(termine=1, antworten=2),
    })
    t = plattform_report_text(p)
    assert "2 aktive Mandanten" in t
    assert "3 bestätigte Termine" in t
    assert "7 Antworten gesamt" in t


def t_gesamtsicht_sortiert_nach_terminen(d):
    p = _plattform(d, {
        "acme": MockRunner(termine=0),
        "beta": MockRunner(termine=3),
    })
    t = plattform_report_text(p)
    # beta (3 Termine) muss vor acme (0 Termine) erscheinen
    assert t.index("beta") < t.index("acme")


def t_gesamtsicht_keine_mandanten(d):
    reg = MandantenRegister(d)
    p = Plattform(reg, bridge_factory=lambda ed: None)
    t = plattform_report_text(p)
    assert "Keine aktiven Mandanten" in t


def t_gesamtsicht_inaktive_nicht_enthalten(d):
    reg = MandantenRegister(d)
    reg.anlegen(Mandant("aktiv", engine_dir=str(d / "e1")))
    reg.anlegen(Mandant("inaktiv", engine_dir=str(d / "e2"), aktiv=False))
    p = Plattform(reg, bridge_factory=lambda ed: None,
                  reporter_factory=lambda ed: None)
    p._runners["aktiv"] = MockRunner(termine=1)
    berichte = plattform_report(p)
    ids = {r["mandant_id"] for r in berichte}
    assert "inaktiv" not in ids
    assert "aktiv" in ids


if __name__ == "__main__":
    print("\n=== Phase F5 — Revenue-Reporting ===\n")
    print("── mandant_report ──")
    test("betriebsbereit: Zahlen korrekt", t_report_betriebsbereit)
    test("nicht eingerichtet → Nullen + Flag", t_report_nicht_eingerichtet)
    test("Text zeigt bestätigte Termine", t_report_text_zeigt_termine)
    test("Text zeigt 'zur Prüfung'", t_report_text_zeigt_pruefen)
    test("Text zeigt 'ohne Bezug' + Termin-Signal", t_report_text_ohne_bezug)
    test("Text: keine Aktivität", t_report_text_keine_aktivitaet)
    test("nicht eingerichtet Text", t_report_nicht_eingerichtet_text)

    print("\n── Gesamtsicht ──")
    test("alle aktiven Mandanten im Report", t_gesamtsicht_alle_mandanten)
    test("Text summiert Termine + Antworten", t_gesamtsicht_text_summiert)
    test("sortiert nach Terminen (absteigend)", t_gesamtsicht_sortiert_nach_terminen)
    test("keine Mandanten", t_gesamtsicht_keine_mandanten)
    test("inaktive nicht enthalten", t_gesamtsicht_inaktive_nicht_enthalten)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
