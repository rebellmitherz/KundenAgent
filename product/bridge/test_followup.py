"""Tests für Phase B.3 — Nachfassen (Bridge).

Beweist: Fällig-Vorschau ist rein lesend; der Nachfass-Versand ist fail-closed
(ohne Bestätigung kein Subprozess) und setzt die Sende-Env nur scoped.
KEIN echter Versand. Aufruf: PYTHONUTF8=1 python product/bridge/test_followup.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from datetime import datetime
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


class SubprocessSpy:
    def __init__(self, rc=0):
        self.aufrufe = []
        self._rc = rc

    def __call__(self, cmd, **kwargs):
        args = cmd[2:] if len(cmd) > 2 else []
        self.aufrufe.append((args, kwargs.get("env")))
        return _FakeProc(self._rc, "ok")


def _engine(tmp: Path, entries=None) -> EngineBridge:
    (tmp / "mine.py").write_text("# dummy", encoding="utf-8")
    out = tmp / "output"
    out.mkdir(parents=True, exist_ok=True)
    if entries is not None:
        (out / "outreach_pipeline.json").write_text(
            json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
    return EngineBridge(tmp)


def _eintrag(firma, sent="m1", reply="none", dnr=False, nf="2026-06-01T10:00:00"):
    return {"company_name": firma, "contact_name": "Chef", "entry_key": firma,
            "sent_message_id": sent, "reply_status": reply, "do_not_resend": dnr,
            "next_followup_at": nf, "last_contacted_at": "2026-05-29T10:00:00",
            "outreach_stage": "ready"}


# ─── Runner ──────────────────────────────────────────────────────────────────

_ok = 0
_fail = 0


def test(name, fn):
    global _ok, _fail
    vorher = os.environ.get("OUTREACH_SEND_CONFIRMED")
    try:
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
        assert os.environ.get("OUTREACH_SEND_CONFIRMED") == vorher, "Env ins globale os.environ geleakt!"
        print(f"  ✓  {name}")
        _ok += 1
    except Exception:
        print(f"  ✗  {name}")
        traceback.print_exc(limit=4)
        _fail += 1


# ─── Fällig-Vorschau (read-only) ────────────────────────────────────────────

JETZT = datetime(2026, 6, 4, 12, 0, 0)


def t_faellig_filtert_korrekt(d):
    eintraege = [
        _eintrag("Faellig GmbH", nf="2026-06-01T10:00:00"),          # fällig (Vergangenheit)
        _eintrag("Zukunft GmbH", nf="2026-12-01T10:00:00"),          # noch nicht fällig
        _eintrag("Hat geantwortet", reply="interested"),             # raus: Antwort da
        _eintrag("Nie gesendet", sent=""),                           # raus: keine erste Mail
        _eintrag("Gesperrt", dnr=True),                              # raus: do_not_resend
    ]
    bridge = _engine(d, eintraege)
    # subprocess darf NIE laufen
    spy = SubprocessSpy(); eb.subprocess.run = spy
    res = bridge.followups_faellig(jetzt=JETZT)
    assert spy.aufrufe == [], "Fällig-Vorschau hat einen Subprozess gestartet!"
    firmen = [r["firma"] for r in res]
    assert firmen == ["Faellig GmbH"], firmen


def t_faellig_leer_ohne_pipeline(d):
    bridge = _engine(d)
    assert bridge.followups_faellig(jetzt=JETZT) == []


def t_faellig_felder_kundenfaehig(d):
    bridge = _engine(d, [_eintrag("Müller Bau")])
    r = bridge.followups_faellig(jetzt=JETZT)[0]
    assert set(r.keys()) == {"firma", "ansprechpartner", "faellig_seit",
                             "zuletzt_kontaktiert", "stufe", "entry_key"}
    assert r["firma"] == "Müller Bau"


# ─── Nachfass-Versand (gated) ────────────────────────────────────────────────

def t_ohne_bestaetigung_kein_subprozess(d):
    spy = SubprocessSpy(); eb.subprocess.run = spy
    bridge = _engine(d, [])
    erg = bridge.followup_ausfuehren(limit=10)   # bestaetigt fehlt
    assert not erg.ok
    assert "abgelehnt" in erg.meldung.lower()
    assert spy.aufrufe == []


def t_mit_bestaetigung_followups_mit_env(d):
    spy = SubprocessSpy(); eb.subprocess.run = spy
    bridge = _engine(d, [])
    erg = bridge.followup_ausfuehren(limit=8, bestaetigt=True)
    assert erg.ok, erg.meldung
    args, env = spy.aufrufe[0]
    assert "--outreach" in args and args[args.index("--outreach") + 1] == "followups"
    assert "8" in args
    assert env is not None and env.get("OUTREACH_SEND_CONFIRMED") == "true"


def t_followup_fehler_ehrlich(d):
    spy = SubprocessSpy(rc=1); eb.subprocess.run = spy
    bridge = _engine(d, [])
    erg = bridge.followup_ausfuehren(limit=5, bestaetigt=True)
    assert not erg.ok
    assert "nachfassen fehlgeschlagen" in erg.meldung.lower()


if __name__ == "__main__":
    print("\n=== Phase B.3 — Nachfassen (Bridge) ===\n")
    _orig = eb.subprocess.run
    try:
        test("Fällig-Vorschau filtert korrekt (read-only)", t_faellig_filtert_korrekt)
        test("Fällig leer ohne Pipeline", t_faellig_leer_ohne_pipeline)
        test("Fällig-Felder kundenfähig", t_faellig_felder_kundenfaehig)
        test("ohne Bestätigung: kein Subprozess", t_ohne_bestaetigung_kein_subprozess)
        test("mit Bestätigung: followups + Sende-Env", t_mit_bestaetigung_followups_mit_env)
        test("Fehler → ehrlich gemeldet", t_followup_fehler_ehrlich)
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
