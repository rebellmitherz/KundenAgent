"""Tests für Phase B.2 — Antworten lesen (Bridge, read-only).

Beweist: rein lesend (kein Subprozess), korrekte Normalisierung + Firma-Join,
Terminwunsch-Erkennung. Aufruf: PYTHONUTF8=1 python product/bridge/test_antworten.py
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


def _engine(tmp: Path, reply_items=None, pipeline_entries=None) -> EngineBridge:
    (tmp / "mine.py").write_text("# dummy", encoding="utf-8")
    out = tmp / "output"
    out.mkdir(parents=True, exist_ok=True)
    if reply_items is not None:
        (out / "reply_queue.json").write_text(
            json.dumps({"items": reply_items, "total": len(reply_items)}, ensure_ascii=False),
            encoding="utf-8",
        )
    if pipeline_entries is not None:
        (out / "outreach_pipeline.json").write_text(
            json.dumps({"entries": pipeline_entries}, ensure_ascii=False),
            encoding="utf-8",
        )
    return EngineBridge(tmp)


# ─── Runner ──────────────────────────────────────────────────────────────────

_ok = 0
_fail = 0


def test(name, fn):
    global _ok, _fail
    # subprocess.run darf NIE aufgerufen werden (rein lesend)
    aufgerufen = {"n": 0}
    orig = eb.subprocess.run
    eb.subprocess.run = lambda *a, **k: aufgerufen.__setitem__("n", aufgerufen["n"] + 1)
    try:
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
        assert aufgerufen["n"] == 0, "antworten_lesen hat einen Subprozess gestartet!"
        print(f"  ✓  {name}")
        _ok += 1
    except Exception:
        print(f"  ✗  {name}")
        traceback.print_exc(limit=4)
        _fail += 1
    finally:
        eb.subprocess.run = orig


# ─── Tests ───────────────────────────────────────────────────────────────────

def t_keine_datei_leer(d):
    bridge = _engine(d)   # keine reply_queue.json
    assert bridge.antworten_lesen() == []


def t_normalisierung_und_terminwunsch(d):
    items = [
        {"entry_key": "k1", "from_email": "chef@mueller-bau.de",
         "inbound_subject": "AW: Ihr Angebot", "inbound_snippet": "Klingt gut, wann?",
         "inbound_class": "interested", "sentiment": "positiv",
         "appointment_ready": True, "appointment_reason": "möchte Termin nächste Woche",
         "reply_sales_category": "hot"},
        {"entry_key": "k2", "from_email": "info@example.com",
         "inbound_subject": "Re: Hallo", "inbound_snippet": "Kein Interesse.",
         "inbound_class": "not_interested", "sentiment": "negativ",
         "appointment_ready": False, "appointment_reason": ""},
    ]
    pipeline = [{"entry_key": "k1", "company_name": "Müller Bau GmbH"}]
    bridge = _engine(d, reply_items=items, pipeline_entries=pipeline)
    res = bridge.antworten_lesen()
    assert len(res) == 2
    # Firma via Join
    assert res[0]["firma"] == "Müller Bau GmbH"
    assert res[0]["terminwunsch"] is True
    assert res[0]["termin_grund"] == "möchte Termin nächste Woche"
    # Fallback auf Domain wenn kein Join
    assert res[1]["firma"] == "example.com"
    assert res[1]["terminwunsch"] is False


def t_limit_greift(d):
    items = [{"entry_key": f"k{i}", "from_email": f"a{i}@x.de",
              "inbound_subject": "s", "inbound_snippet": "x"} for i in range(10)]
    bridge = _engine(d, reply_items=items)
    assert len(bridge.antworten_lesen(limit=3)) == 3


def t_keine_rohdaten_keine_ids_in_anzeige(d):
    """Anzeige enthält keine technischen Felder ausser entry_key (intern)."""
    items = [{"entry_key": "k1", "from_email": "a@x.de", "message_id": "<secret@imap>",
              "inbound_subject": "s", "inbound_snippet": "x", "sent_log_id": "LOG123"}]
    bridge = _engine(d, reply_items=items)
    res = bridge.antworten_lesen()[0]
    assert "message_id" not in res
    assert "sent_log_id" not in res
    assert set(res.keys()) == {"firma", "betreff", "auszug", "klasse", "sentiment",
                               "terminwunsch", "termin_grund", "kategorie", "entry_key"}


def t_kaputte_datei_leer(d):
    bridge = _engine(d)
    (d / "output" / "reply_queue.json").write_text("{kaputt", encoding="utf-8")
    assert bridge.antworten_lesen() == []


if __name__ == "__main__":
    print("\n=== Phase B.2 — Antworten lesen (Bridge, read-only) ===\n")
    test("keine Datei → leer", t_keine_datei_leer)
    test("Normalisierung + Terminwunsch + Firma-Join", t_normalisierung_und_terminwunsch)
    test("Limit greift", t_limit_greift)
    test("keine Roh-IDs in Anzeige", t_keine_rohdaten_keine_ids_in_anzeige)
    test("kaputte Datei → leer", t_kaputte_datei_leer)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
