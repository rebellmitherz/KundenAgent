"""Tests für E — aktiver Antwort-Abruf (process-replies), fail-closed gegen Versand.

OHNE echte Engine/IMAP: subprocess.run gemockt. Beweist, dass der Abruf NIE
senden kann (alle Auto-Send-Gates scoped AUS) und nur abruft + Queue zählt.

Aufruf: PYTHONUTF8=1 python product/bridge/test_abruf.py
"""
from __future__ import annotations

import json
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


class _FakeProc:
    def __init__(self, rc, out=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = ""


class AbrufSpy:
    """Ersetzt subprocess.run: protokolliert Aufrufe, simuliert IMAP-Abruf
    durch Schreiben neuer reply_queue-Items."""

    def __init__(self, tmp: Path, rc=0, neu_items=2):
        self.tmp = tmp
        self.rc = rc
        self.neu_items = neu_items
        self.aufrufe = []   # list[(args, env)]

    def __call__(self, cmd, **kwargs):
        args = cmd[2:] if len(cmd) > 2 else []
        self.aufrufe.append((args, kwargs.get("env")))
        if self.rc == 0 and "--outreach" in args and "process-replies" in args:
            outdir = self.tmp / "output"
            outdir.mkdir(parents=True, exist_ok=True)
            items = [{"entry_key": f"k{i}", "from_email": f"a{i}@x.de",
                      "inbound_subject": "Re", "inbound_snippet": "hi"} for i in range(self.neu_items)]
            (outdir / "reply_queue.json").write_text(
                json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
        return _FakeProc(self.rc, "process-replies ok")


def _bridge(tmp: Path) -> EngineBridge:
    (tmp / "mine.py").write_text("# dummy", encoding="utf-8")
    return EngineBridge(tmp)


_ok = 0
_fail = 0

# Alle Gates, die der Abruf scoped AUS zwingen MUSS
_GATES = ["REPLY_DRY_RUN", "REPLY_AUTO_SEND", "REPLY_AUTO_SEND_CONFIRMED",
          "OUTREACH_SEND_CONFIRMED", "OUTREACH_FULL_AUTO_CONFIRMED"]


def test(name, fn):
    global _ok, _fail
    # Scoping-Leak-Wächter: keine der Gates darf global hängenbleiben
    vorher = {g: os.environ.get(g) for g in _GATES}
    try:
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
        for g in _GATES:
            assert os.environ.get(g) == vorher[g], f"{g} ist ins globale os.environ geleakt!"
        print(f"  ✓  {name}")
        _ok += 1
    except Exception:
        print(f"  ✗  {name}")
        traceback.print_exc(limit=4)
        _fail += 1


# ─── Tests ───────────────────────────────────────────────────────────────────

def t_ruft_process_replies(d):
    spy = AbrufSpy(d); eb.subprocess.run = spy
    erg = _bridge(d).antworten_abrufen(limit=10)
    assert erg.ok, erg.meldung
    args, _ = spy.aufrufe[0]
    assert "--outreach" in args and args[args.index("--outreach")+1] == "process-replies"
    assert "10" in args   # Limit durchgereicht


def t_alle_sende_gates_aus(d):
    spy = AbrufSpy(d); eb.subprocess.run = spy
    _bridge(d).antworten_abrufen()
    _, env = spy.aufrufe[0]
    assert env is not None
    assert env.get("REPLY_DRY_RUN") == "1"
    assert env.get("REPLY_AUTO_SEND") == "false"
    assert env.get("REPLY_AUTO_SEND_CONFIRMED") == "false"
    assert env.get("OUTREACH_SEND_CONFIRMED") == "false"
    assert env.get("OUTREACH_FULL_AUTO_CONFIRMED") == "false"


def t_niemals_send_oder_approve(d):
    spy = AbrufSpy(d); eb.subprocess.run = spy
    _bridge(d).antworten_abrufen()
    aktionen = [a[a.index("--outreach")+1] for a, _ in spy.aufrufe if "--outreach" in a]
    assert "send" not in aktionen
    assert "approve" not in aktionen
    assert "followups" not in aktionen
    assert "full-auto" not in aktionen


def t_zaehlt_neue_antworten(d):
    spy = AbrufSpy(d, neu_items=3); eb.subprocess.run = spy
    erg = _bridge(d).antworten_abrufen()
    assert erg.leads_gefunden == 3       # neu
    assert erg.leads_sauber == 3         # gesamt
    assert "3" in erg.meldung


def t_fehler_ehrlich(d):
    spy = AbrufSpy(d, rc=1); eb.subprocess.run = spy
    erg = _bridge(d).antworten_abrufen()
    assert not erg.ok
    assert "fehlgeschlagen" in erg.meldung.lower()


def t_runner_delegiert(d=None):
    """Runner reicht an die Bridge durch (ohne Subprozess — eigener Mock)."""
    from product.agent.runner import AgentRunner

    class MockBridge:
        def __init__(self): self.gerufen = False
        def antworten_abrufen(self, limit=30):
            self.gerufen = True
            return eb.EngineBrueckenErgebnis(ok=True, leads_gefunden=2, leads_sauber=5, meldung="2 neue")
    mb = MockBridge()
    runner = AgentRunner(mb, data_dir=".")
    res = runner.antworten_abrufen()
    assert mb.gerufen and res["ok"] and res["neu"] == 2 and res["gesamt"] == 5


def t_runner_ohne_bridge(d=None):
    from product.agent.runner import AgentRunner
    res = AgentRunner(None, data_dir=".").antworten_abrufen()
    assert not res["ok"]


def t_watcher_auto_abruf_ruft_ab(d=None):
    """Watcher mit auto_abruf=True ruft runner.antworten_abrufen vor dem Prüfen."""
    from product.agent.watcher import Watcher

    class FakeRunner:
        def __init__(self): self.abgerufen = 0
        def antworten_abrufen(self): self.abgerufen += 1; return {"ok": True}
        def laeufe(self): return []
        def antworten(self): return []
        def nachfass_faellig(self): return []
    fr = FakeRunner()
    w = Watcher(fr, owner_chat_id="1", send_fn=lambda c, t: None, auto_abruf=True)
    w.jetzt_pruefen()
    assert fr.abgerufen == 1

    fr2 = FakeRunner()
    w2 = Watcher(fr2, owner_chat_id="1", send_fn=lambda c, t: None, auto_abruf=False)
    w2.jetzt_pruefen()
    assert fr2.abgerufen == 0   # ohne Flag kein Abruf


if __name__ == "__main__":
    print("\n=== E — Aktiver Antwort-Abruf (fail-closed gegen Versand) ===\n")
    _orig = eb.subprocess.run
    try:
        test("ruft process-replies mit Limit", t_ruft_process_replies)
        test("ALLE Auto-Send-Gates scoped AUS", t_alle_sende_gates_aus)
        test("niemals send/approve/followups/full-auto", t_niemals_send_oder_approve)
        test("zählt neue Antworten", t_zaehlt_neue_antworten)
        test("Fehler ehrlich gemeldet", t_fehler_ehrlich)
    finally:
        eb.subprocess.run = _orig
    test("Runner delegiert an Bridge", t_runner_delegiert)
    test("Runner ohne Bridge → ok=False", t_runner_ohne_bridge)
    test("Watcher auto_abruf ruft ab", t_watcher_auto_abruf_ruft_ab)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
