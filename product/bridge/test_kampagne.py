"""Tests für Phase C — bridge.kampagne_rohdaten (read-only).

Beweist: rein lesend, korrekte Normalisierung, reply_queue-Join, Kampagnen-Filter.
Aufruf: PYTHONUTF8=1 python product/bridge/test_kampagne.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import product.bridge.engine_bridge as eb
from product.bridge.engine_bridge import EngineBridge


def _engine(tmp: Path, entries=None, reply_items=None) -> EngineBridge:
    (tmp / "mine.py").write_text("# dummy", encoding="utf-8")
    out = tmp / "output"
    out.mkdir(parents=True, exist_ok=True)
    if entries is not None:
        (out / "outreach_pipeline.json").write_text(
            json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
    if reply_items is not None:
        (out / "reply_queue.json").write_text(
            json.dumps({"items": reply_items}, ensure_ascii=False), encoding="utf-8")
    return EngineBridge(tmp)


def _eintrag(ek, firma, sent=None, ready="yes", dnr=False, camps=None, email=""):
    return {"entry_key": ek, "company_name": firma, "city": "Köln",
            "contact_name": "Chef", "sent_message_id": sent,
            "ready_to_send": ready, "do_not_resend": dnr,
            "contacted_in_campaigns": camps or [], "email": email}


# ─── Runner ──────────────────────────────────────────────────────────────────

_ok = 0
_fail = 0


def test(name, fn):
    global _ok, _fail
    spy = {"n": 0}
    orig = eb.subprocess.run
    eb.subprocess.run = lambda *a, **k: spy.__setitem__("n", spy["n"] + 1)
    try:
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
        assert spy["n"] == 0, "kampagne_rohdaten hat einen Subprozess gestartet!"
        print(f"  ✓  {name}")
        _ok += 1
    except Exception:
        print(f"  ✗  {name}")
        traceback.print_exc(limit=4)
        _fail += 1
    finally:
        eb.subprocess.run = orig


# ─── Tests ───────────────────────────────────────────────────────────────────

def t_leer_ohne_pipeline(d):
    bridge = _engine(d)
    roh = bridge.kampagne_rohdaten()
    assert roh["entries"] == [] and roh["antwort_keys"] == [] and roh["termin_keys"] == []
    assert roh["antwort_domains"] == [] and roh["termin_domains"] == []
    assert roh["antwort_ohne_bezug"] == 0 and roh["termin_ohne_bezug"] == 0


def t_normalisierung_und_flags(d):
    entries = [
        _eintrag("a", "Alpha", sent="m1"),
        _eintrag("b", "Beta", sent=None, ready="yes"),
        _eintrag("c", "Gamma", sent=None, ready="review"),
    ]
    bridge = _engine(d, entries)
    roh = bridge.kampagne_rohdaten()
    e = {x["entry_key"]: x for x in roh["entries"]}
    assert e["a"]["gesendet"] is True and e["a"]["firma"] == "Alpha"
    assert e["b"]["gesendet"] is False and e["b"]["bereit"] is True
    assert e["c"]["bereit"] is False     # review ist nicht bereit


def t_reply_join(d):
    entries = [_eintrag("a", "Alpha", sent="m1"), _eintrag("b", "Beta", sent="m2")]
    reply = [{"entry_key": "a", "appointment_ready": True},
             {"entry_key": "b", "appointment_ready": False}]
    bridge = _engine(d, entries, reply_items=reply)
    roh = bridge.kampagne_rohdaten()
    assert roh["antwort_keys"] == ["a", "b"]
    assert roh["termin_keys"] == ["a"]


def t_kampagnen_filter(d):
    entries = [
        _eintrag("a", "Alpha", camps=["cmp-1"]),
        _eintrag("b", "Beta", camps=["cmp-2"]),
        _eintrag("c", "Gamma", camps=["cmp-1", "cmp-2"]),
    ]
    bridge = _engine(d, entries)
    nur1 = bridge.kampagne_rohdaten(campaign="cmp-1")
    firmen = {x["firma"] for x in nur1["entries"]}
    assert firmen == {"Alpha", "Gamma"}


def t_dnr_nicht_bereit(d):
    bridge = _engine(d, [_eintrag("a", "Alpha", ready="yes", dnr=True)])
    roh = bridge.kampagne_rohdaten()
    assert roh["entries"][0]["bereit"] is False


# ─── F2: Domain-Join + 'ohne Bezug' ──────────────────────────────────────────

def t_domain_join_rettet_anderen_key(d):
    """Reply hat anderen entry_key, aber gleiche Domain → zählt als Bezug + Domain-Set."""
    entries = [_eintrag("a", "Alpha", sent="m1", email="chef@alpha.de")]
    reply = [{"entry_key": "ZZZ-anderer-key", "from_email": "info@alpha.de",
              "appointment_ready": True}]
    roh = _engine(d, entries, reply_items=reply).kampagne_rohdaten()
    assert "alpha.de" in roh["antwort_domains"]
    assert "alpha.de" in roh["termin_domains"]
    assert roh["antwort_ohne_bezug"] == 0      # Domain matcht → Bezug da
    assert roh["termin_ohne_bezug"] == 0


def t_orphan_ohne_bezug_gezaehlt(d):
    """Reply ohne passenden Key UND ohne passende Domain → ehrlich als 'ohne Bezug'."""
    entries = [_eintrag("a", "Alpha", sent="m1", email="chef@alpha.de")]
    reply = [{"entry_key": "fremd", "from_email": "we@fremdfirma.de",
              "appointment_ready": True}]
    roh = _engine(d, entries, reply_items=reply).kampagne_rohdaten()
    assert roh["antwort_ohne_bezug"] == 1
    assert roh["termin_ohne_bezug"] == 1
    assert roh["antwort_keys"] == ["fremd"]    # Key bleibt erfasst (für Anzeige)
    assert "fremdfirma.de" in roh["antwort_domains"]


def t_from_email_actual_bevorzugt(d):
    entries = [_eintrag("a", "Alpha", email="chef@alpha.de")]
    reply = [{"entry_key": "x", "from_email": "noreply@relay.com",
              "from_email_actual": "info@alpha.de", "appointment_ready": False}]
    roh = _engine(d, entries, reply_items=reply).kampagne_rohdaten()
    assert "alpha.de" in roh["antwort_domains"]   # actual gewinnt über relay
    assert roh["antwort_ohne_bezug"] == 0


if __name__ == "__main__":
    print("\n=== Phase C — bridge.kampagne_rohdaten (read-only) ===\n")
    test("leer ohne Pipeline", t_leer_ohne_pipeline)
    test("Normalisierung + bereit/gesendet-Flags", t_normalisierung_und_flags)
    test("reply_queue-Join (antwort/termin)", t_reply_join)
    test("Kampagnen-Filter", t_kampagnen_filter)
    test("do_not_resend → nicht bereit", t_dnr_nicht_bereit)
    test("F2: Domain-Join rettet anderen Key", t_domain_join_rettet_anderen_key)
    test("F2: Orphan ohne Bezug gezählt", t_orphan_ohne_bezug_gezaehlt)
    test("F2: from_email_actual bevorzugt", t_from_email_actual_bevorzugt)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
