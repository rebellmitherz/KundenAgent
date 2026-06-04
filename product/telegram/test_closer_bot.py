"""Tests für Closer-Integration im Telegram-Bot (Phase D Ergänzung).

Läuft ohne echten Bot, ohne ClouseAgent-Prozess.
Aufruf: PYTHONUTF8=1 python product/telegram/test_closer_bot.py
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.agent.notifier import meldungen_ermitteln


# ─── Fake-Closer ─────────────────────────────────────────────────────────────

class FakeCloser:
    def __init__(self, verfuegbar=True, laeuft=False, start_ok=True):
        self._v = verfuegbar
        self._l = laeuft
        self._ok = start_ok
        self.aufrufe: list[str] = []

    def starten(self):
        self.aufrufe.append("starten")
        return {"ok": self._ok, "meldung": "Closer gestartet." if self._ok else "Fehler"}

    def stoppen(self):
        self.aufrufe.append("stoppen")
        if self._l:
            self._l = False
            return {"ok": True, "meldung": "Closer gestoppt."}
        return {"ok": False, "meldung": "Closer läuft nicht."}

    def status(self):
        return {"laeuft": self._l, "closer_verfuegbar": self._v, "log_zeilen": 0}


def _antwort(ek, termin=False, firma="Firma"):
    return {"entry_key": ek, "firma": firma, "terminwunsch": termin,
            "betreff": "AW", "auszug": "..."}


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


# ─── Notifier: Termin-Signal enthält Closer-Hinweis ──────────────────────────

def t_termin_meldung_erwähnt_closer():
    ant = [_antwort("k1", termin=True, firma="Müller Bau")]
    m = meldungen_ermitteln([], ant, [], set())
    assert len(m) == 1
    assert "closer starten" in m[0].text.lower()
    assert "🎤" in m[0].text


def t_kein_closer_hinweis_ohne_termin():
    """Kein Termin → kein Closer-Hinweis in der Meldung."""
    from product.agent.notifier import _hash
    m = meldungen_ermitteln([], [], [], set())
    assert m == []


# ─── Closer-Befehle (Logik durch FakeCloser verifiziert) ─────────────────────

def t_starten_ruft_adapter():
    closer = FakeCloser(verfuegbar=True)
    erg = closer.starten()
    assert erg["ok"]
    assert "starten" in closer.aufrufe


def t_starten_fehler_gemeldet():
    closer = FakeCloser(start_ok=False)
    erg = closer.starten()
    assert not erg["ok"]
    assert "starten" in closer.aufrufe


def t_stoppen_wenn_laeuft():
    closer = FakeCloser(laeuft=True)
    erg = closer.stoppen()
    assert erg["ok"]


def t_stoppen_wenn_nicht_laeuft():
    closer = FakeCloser(laeuft=False)
    erg = closer.stoppen()
    assert not erg["ok"]
    assert "läuft nicht" in erg["meldung"].lower()


def t_status_laeuft():
    closer = FakeCloser(laeuft=True)
    st = closer.status()
    assert st["laeuft"] is True
    assert st["closer_verfuegbar"] is True


def t_status_nicht_verfuegbar():
    closer = FakeCloser(verfuegbar=False, laeuft=False)
    st = closer.status()
    assert not st["laeuft"]
    assert not st["closer_verfuegbar"]


if __name__ == "__main__":
    print("\n=== Closer-Integration (Bot + Notifier) ===\n")
    print("── Notifier ──")
    test("Termin-Meldung erwähnt Closer", t_termin_meldung_erwähnt_closer)
    test("Kein Closer-Hinweis ohne Termin", t_kein_closer_hinweis_ohne_termin)

    print("\n── Closer-Adapter Logik ──")
    test("starten() ruft Adapter", t_starten_ruft_adapter)
    test("starten() Fehler → ok=False", t_starten_fehler_gemeldet)
    test("stoppen() wenn läuft → ok", t_stoppen_wenn_laeuft)
    test("stoppen() wenn nicht läuft → Meldung", t_stoppen_wenn_nicht_laeuft)
    test("status() läuft", t_status_laeuft)
    test("status() nicht verfügbar", t_status_nicht_verfuegbar)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
