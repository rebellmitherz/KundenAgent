"""Tests für Phase D — Notifier + Watcher.

Läuft ohne Telegram, ohne Engine, ohne Key.
Aufruf: PYTHONUTF8=1 python product/agent/test_notifier.py
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.agent.notifier import Meldung, meldungen_ermitteln
from product.agent.watcher import Watcher


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _lauf(aid, status, sendbar=10, ziel=100, zg="Handwerker", reg="NRW"):
    return {"auftrags_id": aid, "status": status,
            "auftrag": {"zielgruppe": zg, "region": reg, "lead_anzahl": ziel},
            "funnel": {"sendbar": sendbar, "ziel": ziel}}


def _antwort(ek, termin=False, firma="Firma"):
    return {"entry_key": ek, "firma": firma, "terminwunsch": termin,
            "betreff": "AW", "auszug": "..."}


def _nf(ek, firma="Lead"):
    return {"entry_key": ek, "firma": firma, "faellig_seit": "2026-06-01T10:00:00",
            "zuletzt_kontaktiert": "2026-05-29T10:00:00", "stufe": "ready"}


# ─── Fake-Runner ─────────────────────────────────────────────────────────────

class FakeRunner:
    def __init__(self, laeufe=None, antworten=None, nachfass=None):
        self._l = laeufe or []
        self._a = antworten or []
        self._n = nachfass or []

    def laeufe(self): return self._l
    def antworten(self, limit=30): return self._a
    def nachfass_faellig(self, limit=50): return self._n


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


# ─── meldungen_ermitteln ─────────────────────────────────────────────────────

def t_keine_meldung_wenn_leer():
    m = meldungen_ermitteln([], [], [], set())
    assert m == []


def t_termin_hat_prio_1():
    ant = [_antwort("k1", termin=True, firma="Alpha GmbH")]
    m = meldungen_ermitteln([], ant, [], set())
    assert len(m) == 1
    assert m[0].prioritaet == 1
    assert "Termin" in m[0].text
    assert "Alpha GmbH" in m[0].text
    assert "👉" in m[0].text


def t_hartes_tor_prio_2():
    l = [_lauf("id1", "wartet_auf_mensch", sendbar=95, ziel=100)]
    m = meldungen_ermitteln(l, [], [], set())
    assert len(m) == 1
    assert m[0].prioritaet == 2
    assert "95/100" in m[0].text
    assert "freigeben" in m[0].text.lower()


def t_nachfassen_prio_3():
    m = meldungen_ermitteln([], [], [_nf("k1", "Beta GmbH")], set())
    assert len(m) == 1
    assert m[0].prioritaet == 3
    assert "Beta GmbH" in m[0].text
    assert "Nachfassen" in m[0].text


def t_sortierung_termin_vor_tor():
    l = [_lauf("id1", "wartet_auf_mensch")]
    ant = [_antwort("k1", termin=True)]
    m = meldungen_ermitteln(l, ant, [], set())
    assert len(m) == 2
    assert m[0].prioritaet == 1   # Termin zuerst
    assert m[1].prioritaet == 2   # Tor danach


def t_deduplizierung():
    ant = [_antwort("k1", termin=True)]
    m1 = meldungen_ermitteln([], ant, [], set())
    sig = m1[0].signatur
    # Zweiter Aufruf mit bereits gesendeter Signatur → nichts mehr
    m2 = meldungen_ermitteln([], ant, [], {sig})
    assert m2 == []


def t_kein_tor_wenn_status_nicht_am_tor():
    l = [_lauf("id1", "gesendet"), _lauf("id2", "aufgegeben")]
    m = meldungen_ermitteln(l, [], [], set())
    assert m == []


def t_mehrere_termine():
    ant = [_antwort(f"k{i}", termin=True, firma=f"Firma {i}") for i in range(5)]
    m = meldungen_ermitteln([], ant, [], set())
    assert len(m) == 1
    assert "Termin-Signal" in m[0].text
    assert "Firma 0" in m[0].text   # mind. eine Firma im Text


def t_signatur_aendert_sich_bei_neuen_leads():
    nf1 = [_nf("k1")]
    nf2 = [_nf("k1"), _nf("k2")]
    m1 = meldungen_ermitteln([], [], nf1, set())
    sig1 = m1[0].signatur
    m2 = meldungen_ermitteln([], [], nf2, {sig1})
    # Neue Signatur wegen k2 → wird trotz sig1 gesendet
    assert len(m2) == 1
    assert m2[0].signatur != sig1


# ─── Watcher ─────────────────────────────────────────────────────────────────

def t_watcher_sendet_an_owner():
    gesendet = []
    runner = FakeRunner(antworten=[_antwort("k1", termin=True, firma="Müller Bau")])
    w = Watcher(runner, "owner123", lambda cid, txt: gesendet.append((cid, txt)), intervall_sek=99)
    texte = w.jetzt_pruefen()
    assert len(texte) == 1
    assert "Müller Bau" in texte[0]
    assert len(gesendet) == 1
    assert gesendet[0][0] == "owner123"


def t_watcher_keine_duplikate():
    gesendet = []
    runner = FakeRunner(laeufe=[_lauf("id1", "wartet_auf_mensch")])
    w = Watcher(runner, "owner", lambda c, t: gesendet.append(t), intervall_sek=99)
    w.jetzt_pruefen()
    w.jetzt_pruefen()   # zweites Mal: gleiche Signatur → nichts mehr
    assert len(gesendet) == 1


def t_watcher_thread_laeuft_und_stoppt():
    runner = FakeRunner()
    w = Watcher(runner, "owner", lambda c, t: None, intervall_sek=60)
    w.starten()
    assert w._thread and w._thread.is_alive()
    w.stop()
    w._thread.join(timeout=1.0)
    assert not w._thread.is_alive()


def t_watcher_fehler_sturzt_nicht_ab():
    def kaputte_send(cid, txt):
        raise RuntimeError("Telegram down")
    runner = FakeRunner(antworten=[_antwort("k1", termin=True)])
    w = Watcher(runner, "owner", kaputte_send, intervall_sek=99)
    # Darf keinen Exception werfen
    texte = w.jetzt_pruefen()
    assert texte == []   # nichts gesendet, aber kein Crash


if __name__ == "__main__":
    print("\n=== Phase D — Notifier + Watcher ===\n")
    print("── meldungen_ermitteln ──")
    test("leer → keine Meldung", t_keine_meldung_wenn_leer)
    test("Termin → Prio 1 mit Firma + CTA", t_termin_hat_prio_1)
    test("Hartes Tor → Prio 2 mit Zahlen", t_hartes_tor_prio_2)
    test("Nachfassen → Prio 3", t_nachfassen_prio_3)
    test("Sortierung: Termin vor Tor", t_sortierung_termin_vor_tor)
    test("Deduplizierung: gleiche Signatur → nichts", t_deduplizierung)
    test("Kein Tor wenn Status nicht am Tor", t_kein_tor_wenn_status_nicht_am_tor)
    test("Mehrere Termine in einer Meldung", t_mehrere_termine)
    test("Signatur ändert sich bei neuen Leads", t_signatur_aendert_sich_bei_neuen_leads)

    print("\n── Watcher ──")
    test("sendet an Owner-Chat-ID", t_watcher_sendet_an_owner)
    test("keine Duplikate bei zweitem Aufruf", t_watcher_keine_duplikate)
    test("Thread läuft und stoppt sauber", t_watcher_thread_laeuft_und_stoppt)
    test("Telegram-Fehler → kein Absturz", t_watcher_fehler_sturzt_nicht_ab)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
