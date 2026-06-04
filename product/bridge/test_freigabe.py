"""Tests für Phase B.1 — das harte Sende-Tor in der Bridge.

Beweist fail-closed-Verhalten OHNE echte Engine: subprocess.run wird gemockt,
es wird NIE wirklich gesendet. Aufruf: PYTHONUTF8=1 python product/bridge/test_freigabe.py

Kernaussagen:
  - Ohne bestaetigt=True: kein Approve, kein Send, kein Subprozess.
  - Mit bestaetigt=True: approve OHNE Sende-Env, send MIT OUTREACH_SEND_CONFIRMED.
  - Die Sende-Env ist nur scoped (nie im globalen os.environ).
  - Approve-/Send-Fehler werden ehrlich gemeldet.
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import product.bridge.engine_bridge as eb
from product.bridge.engine_bridge import EngineBridge


# ─── Mock-Infrastruktur ──────────────────────────────────────────────────────


class _FakeProc:
    def __init__(self, rc, out=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = ""


class SubprocessSpy:
    """Ersetzt subprocess.run und protokolliert jeden Aufruf (args + env)."""

    def __init__(self, rc_map=None):
        self.aufrufe = []          # list[(args_list, env_dict_or_None)]
        self._rc_map = rc_map or {}

    def __call__(self, cmd, **kwargs):
        args = cmd[2:] if len(cmd) > 2 else []   # nach [python, mine.py]
        self.aufrufe.append((args, kwargs.get("env")))
        # Returncode nach Aktion bestimmen (approve/send), Standard 0
        aktion = ""
        if "--outreach" in args:
            aktion = args[args.index("--outreach") + 1]
        rc = self._rc_map.get(aktion, 0)
        return _FakeProc(rc, f"{aktion} ok")


def _bridge_mit_spy(tmp: Path, spy: SubprocessSpy) -> EngineBridge:
    (tmp / "mine.py").write_text("# dummy", encoding="utf-8")
    # status_lesen liest Dateien — ohne Pipeline gibt es 0, das genügt.
    bridge = EngineBridge(tmp)
    return bridge


# ─── Runner ──────────────────────────────────────────────────────────────────

_ok = 0
_fail = 0


def test(name, fn):
    global _ok, _fail
    # os.environ sichern, um Scoping-Leaks zu erkennen
    vorher = os.environ.get("OUTREACH_SEND_CONFIRMED")
    try:
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
        # Scoping-Garantie: globale Env darf sich NIE geändert haben
        assert os.environ.get("OUTREACH_SEND_CONFIRMED") == vorher, \
            "OUTREACH_SEND_CONFIRMED ist ins globale os.environ geleakt!"
        print(f"  ✓  {name}")
        _ok += 1
    except Exception:
        print(f"  ✗  {name}")
        traceback.print_exc(limit=4)
        _fail += 1


# ─── Tests ───────────────────────────────────────────────────────────────────

def t_ohne_bestaetigung_kein_subprozess(d):
    spy = SubprocessSpy()
    eb.subprocess.run = spy
    bridge = _bridge_mit_spy(d, spy)
    erg = bridge.freigabe_ausfuehren(limit=10)   # bestaetigt fehlt → False
    assert not erg.ok
    assert "abgelehnt" in erg.meldung.lower()
    assert spy.aufrufe == [], "Es wurde ein Subprozess gestartet trotz fehlender Freigabe!"


def t_bestaetigung_false_explizit(d):
    spy = SubprocessSpy()
    eb.subprocess.run = spy
    bridge = _bridge_mit_spy(d, spy)
    erg = bridge.freigabe_ausfuehren(limit=10, bestaetigt=False)
    assert not erg.ok
    assert spy.aufrufe == []


def t_mit_bestaetigung_approve_dann_send(d):
    spy = SubprocessSpy()
    eb.subprocess.run = spy
    bridge = _bridge_mit_spy(d, spy)
    erg = bridge.freigabe_ausfuehren(limit=7, bestaetigt=True)
    assert erg.ok, erg.meldung

    # Genau zwei Aktionen, in Reihenfolge approve → send
    aktionen = [a[a.index("--outreach") + 1] for a, _ in spy.aufrufe]
    assert aktionen == ["approve", "send"], aktionen


def t_send_env_nur_beim_send(d):
    spy = SubprocessSpy()
    eb.subprocess.run = spy
    bridge = _bridge_mit_spy(d, spy)
    bridge.freigabe_ausfuehren(limit=5, bestaetigt=True)

    approve_args, approve_env = spy.aufrufe[0]
    send_args, send_env = spy.aufrufe[1]

    # Approve: keine Sende-Bestätigung
    assert approve_env is None or approve_env.get("OUTREACH_SEND_CONFIRMED") is None
    # Send: Sende-Bestätigung gesetzt
    assert send_env is not None and send_env.get("OUTREACH_SEND_CONFIRMED") == "true"
    # Limit korrekt durchgereicht
    assert "5" in send_args


def t_approve_fehler_kein_send(d):
    spy = SubprocessSpy(rc_map={"approve": 1})   # approve schlägt fehl
    eb.subprocess.run = spy
    bridge = _bridge_mit_spy(d, spy)
    erg = bridge.freigabe_ausfuehren(limit=5, bestaetigt=True)
    assert not erg.ok
    assert "approve" in erg.meldung.lower()
    aktionen = [a[a.index("--outreach") + 1] for a, _ in spy.aufrufe]
    assert "send" not in aktionen, "Nach Approve-Fehler wurde trotzdem gesendet!"


def t_send_fehler_ehrlich(d):
    spy = SubprocessSpy(rc_map={"send": 1})
    eb.subprocess.run = spy
    bridge = _bridge_mit_spy(d, spy)
    erg = bridge.freigabe_ausfuehren(limit=5, bestaetigt=True)
    assert not erg.ok
    assert "send" in erg.meldung.lower()


# ─── Haupt-Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n=== Phase B.1 — Hartes Sende-Tor (Bridge) ===\n")
    _orig = eb.subprocess.run
    try:
        test("ohne Bestätigung: kein Subprozess", t_ohne_bestaetigung_kein_subprozess)
        test("bestaetigt=False explizit: nichts", t_bestaetigung_false_explizit)
        test("mit Bestätigung: approve → send", t_mit_bestaetigung_approve_dann_send)
        test("Sende-Env NUR beim Send-Schritt", t_send_env_nur_beim_send)
        test("Approve-Fehler → kein Send", t_approve_fehler_kein_send)
        test("Send-Fehler → ehrlich gemeldet", t_send_fehler_ehrlich)
    finally:
        eb.subprocess.run = _orig

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
