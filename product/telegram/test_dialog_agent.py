"""Tests für die Agent-Anbindung im Dialog (Phase A.5).

Prüft die additive Verdrahtung in dialog.py — OHNE echte Engine, OHNE Key.
Aufruf: PYTHONUTF8=1 python product/telegram/test_dialog_agent.py

Fokus:
  - Rückwärtskompatibilität: DialogManager ohne agent_runner unverändert
  - Agent-Worker: läuft, sendet kundenfähigen Text, setzt Zustand auf IDLE
  - Agent-Worker: Ausnahme → ruhige Meldung, kein Crash, IDLE
  - Vollständiger bestätigter Durchlauf → Agent wird aufgerufen (nicht die Suche)
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.operator.confirm import ConfirmGate
from product.operator.intake import OperatorIntake
from product.operator.order_schema import Auftrag
from product.telegram.dialog import DialogManager, DialogModus


# ─── Mocks ───────────────────────────────────────────────────────────────────


class FakeBridge:
    """Minimaler Bridge-Ersatz: nur engine_dir wird beim Aufbau gebraucht
    (Reporter + TargetFillManager speichern den Pfad, lesen nichts)."""

    def __init__(self, engine_dir: Path):
        self.engine_dir = engine_dir

    def status_lesen(self) -> dict:
        return {"sendable": 0, "pipeline_total": 0, "sent_total": 0}


@dataclass
class FakeLaufergebnis:
    _text: str
    def kundentext(self) -> str:
        return self._text


class FakeRunner:
    """Erfasst, ob/mit-welchem Auftrag der Agent gestartet wurde."""

    def __init__(self, text="🔔 Deine Entscheidung ist gefragt\n\n950 Leads bereit.", fehler=False):
        self.aufrufe: list[Auftrag] = []
        self._text = text
        self._fehler = fehler

    def starten(self, auftrag: Auftrag) -> FakeLaufergebnis:
        self.aufrufe.append(auftrag)
        if self._fehler:
            raise RuntimeError("Engine weg (Test)")
        return FakeLaufergebnis(self._text)


def _mgr(tmp: Path, runner=None, gesendet=None) -> DialogManager:
    bridge = FakeBridge(tmp)
    sammeln = gesendet if gesendet is not None else []
    mgr = DialogManager(
        intake=OperatorIntake(llm_fn=None),
        gate=ConfirmGate(),
        bridge=bridge,
        orders_dir=tmp / "orders",
        send_fn=lambda cid, txt: sammeln.append((cid, txt)),
        agent_runner=runner,
    )
    return mgr


def _auftrag_bestaetigt() -> Auftrag:
    a = Auftrag(zielgruppe="Handwerker", region="NRW", lead_anzahl=1000, angebot="Websites")
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

def t_rueckwaertskompatibel_ohne_runner(d):
    """Ohne agent_runner: Konstruktor funktioniert, Attribut ist None."""
    mgr = _mgr(d, runner=None)
    assert mgr._agent_runner is None


def t_agent_worker_sendet_kundentext(d):
    gesendet = []
    runner = FakeRunner(text="🔔 Deine Entscheidung ist gefragt\n\n950 Leads bereit.")
    mgr = _mgr(d, runner=runner, gesendet=gesendet)
    auftrag = _auftrag_bestaetigt()
    mgr._agent_im_hintergrund("chat1", auftrag)

    assert runner.aufrufe == [auftrag]
    texte = [t for _, t in gesendet]
    assert any("Entscheidung ist gefragt" in t for t in texte)
    # Kein Technik-Leak
    for t in texte:
        for w in ("mine.py", "Traceback", "Exception", "Bridge"):
            assert w not in t
    # Zustand zurück auf IDLE
    assert mgr._zustand("chat1").modus == DialogModus.IDLE


def t_agent_worker_fehler_ruhig(d):
    gesendet = []
    runner = FakeRunner(fehler=True)
    mgr = _mgr(d, runner=runner, gesendet=gesendet)
    mgr._agent_im_hintergrund("chat1", _auftrag_bestaetigt())
    texte = [t for _, t in gesendet]
    assert any("abbrechen" in t.lower() for t in texte)
    # Kein roher Fehlertext / keine Technik
    for t in texte:
        assert "Engine weg (Test)" not in t
        assert "RuntimeError" not in t
    assert mgr._zustand("chat1").modus == DialogModus.IDLE


def t_confirming_ja_ruft_agent(d):
    """CONFIRMING + 'ja starten' → Auftrag bestätigt → Agent (statt Suche) läuft.

    Der Intake wird hier umgangen (anderswo getestet) — Fokus ist die
    Bestätigungs→Agent-Weiche und der Hintergrund-Lauf.
    """
    from product.telegram.dialog import ChatZustand

    gesendet = []
    runner = FakeRunner()
    mgr = _mgr(d, runner=runner, gesendet=gesendet)

    # CONFIRMING direkt aufsetzen: ein ENTWURF-Auftrag wartet auf Bestätigung.
    z = mgr._zustand("chat1")
    z.modus = DialogModus.CONFIRMING
    z.auftrag = Auftrag(zielgruppe="Handwerker", region="NRW",
                        lead_anzahl=1000, angebot="Websites")

    mgr.verarbeite("chat1", "ja, starten")   # → BESTAETIGT → Agent-Thread

    # Auf den Hintergrund-Thread warten (kurzes Polling)
    for _ in range(100):
        if runner.aufrufe:
            break
        time.sleep(0.02)
    assert len(runner.aufrufe) == 1, "Agent wurde nicht aufgerufen"
    assert runner.aufrufe[0].zielgruppe == "Handwerker"
    # Bestätigungs-Text erwähnt die eigenständige Kampagne
    texte = [t for _, t in gesendet]
    assert any("übernehme die Kampagne" in t for t in texte)


if __name__ == "__main__":
    print("\n=== Phase A.5 — Dialog-Agent-Anbindung ===\n")
    test("rückwärtskompatibel ohne Runner", t_rueckwaertskompatibel_ohne_runner)
    test("Agent-Worker sendet Kundentext, IDLE", t_agent_worker_sendet_kundentext)
    test("Agent-Worker Fehler → ruhig, IDLE", t_agent_worker_fehler_ruhig)
    test("CONFIRMING + ja → Agent (nicht Suche)", t_confirming_ja_ruft_agent)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
