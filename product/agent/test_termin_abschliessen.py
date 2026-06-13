"""Tests für 'Termin abschließen' (erledigt.py + Runner) und die Detail-Berichte.

Läuft OHNE Engine. Aufruf: PYTHONUTF8=1 python product/agent/test_termin_abschliessen.py
"""
from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.agent.erledigt import ErledigtSpeicher
from product.agent.replies import (antwort_detail_bericht, termin_detail_bericht,
                                    termine)
from product.agent.runner import AgentRunner


def _antwort(firma, key=None, termin=False, grund="", auto=False,
             von="", postfach="", gesendet=""):
    return {"firma": firma, "betreff": "Re: Angebot", "auszug": "Hallo, danke...",
            "klasse": "positive" if termin else "neutral", "sentiment": "",
            "terminwunsch": termin, "termin_grund": grund, "kategorie": "",
            "entry_key": key or firma, "von": von, "postfach": postfach,
            "gesendet_am": gesendet, "auto_antwort": auto}


class MockBridge:
    def __init__(self, antworten):
        self._a = antworten

    def antworten_lesen(self, limit=30):
        return self._a[:limit]


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


# ─── ErledigtSpeicher ────────────────────────────────────────────────────────

def t_speicher_neu_und_persistent():
    with tempfile.TemporaryDirectory() as d:
        s = ErledigtSpeicher(d)
        assert not s.ist_erledigt("k1")
        assert s.abschliessen("k1", "Müller") is True
        assert s.abschliessen("k1", "Müller") is False  # schon da
        assert s.ist_erledigt("k1")
        # Neue Instanz liest dieselbe Datei
        s2 = ErledigtSpeicher(d)
        assert s2.ist_erledigt("k1")
        assert s2.erledigte_keys() == {"k1"}


def t_speicher_leerer_key():
    with tempfile.TemporaryDirectory() as d:
        s = ErledigtSpeicher(d)
        assert s.abschliessen("") is False
        assert not s.ist_erledigt("")


def t_speicher_wieder_oeffnen():
    with tempfile.TemporaryDirectory() as d:
        s = ErledigtSpeicher(d)
        s.abschliessen("k1", "X")
        assert s.wieder_oeffnen("k1") is True
        assert not s.ist_erledigt("k1")
        assert s.wieder_oeffnen("k1") is False


def t_kaputte_datei_robust():
    with tempfile.TemporaryDirectory() as d:
        pfad = Path(d) / "agent" / "erledigte_termine.json"
        pfad.parent.mkdir(parents=True)
        pfad.write_text("{kaputt", encoding="utf-8")
        s = ErledigtSpeicher(d)
        assert s.erledigte_keys() == set()
        assert s.abschliessen("k1") is True   # repariert sich


# ─── Runner: termin_abschliessen + Filterung ─────────────────────────────────

def t_runner_termin_abschliessen():
    with tempfile.TemporaryDirectory() as d:
        bridge = MockBridge([_antwort("artundweise.de", termin=True, grund="positive_reply")])
        runner = AgentRunner(bridge, data_dir=d)
        assert len(runner.termin_signale()) == 1
        erg = runner.termin_abschliessen("artundweise")
        assert erg["ok"] is True
        assert len(runner.termin_signale()) == 0   # verschwindet
        # In antworten() ist die Antwort weiter da, aber erledigt-markiert
        markiert = [a for a in runner.antworten() if a["firma"] == "artundweise.de"][0]
        assert markiert["erledigt"] is True


def t_runner_abschliessen_per_key():
    with tempfile.TemporaryDirectory() as d:
        bridge = MockBridge([_antwort("Firma X", key="abc123", termin=True)])
        runner = AgentRunner(bridge, data_dir=d)
        erg = runner.termin_abschliessen("abc123")
        assert erg["ok"] is True


def t_runner_abschliessen_nicht_gefunden():
    with tempfile.TemporaryDirectory() as d:
        bridge = MockBridge([_antwort("Müller", termin=True)])
        runner = AgentRunner(bridge, data_dir=d)
        erg = runner.termin_abschliessen("gibtsnicht")
        assert erg["ok"] is False
        assert "Müller" in erg["meldung"]   # nennt die offenen


def t_runner_abschliessen_mehrdeutig():
    with tempfile.TemporaryDirectory() as d:
        bridge = MockBridge([_antwort("Müller Bau", termin=True),
                             _antwort("Müller IT", termin=True)])
        runner = AgentRunner(bridge, data_dir=d)
        erg = runner.termin_abschliessen("müller")
        assert erg["ok"] is False
        assert "Mehrere" in erg["meldung"]


def t_runner_abschliessen_leer():
    with tempfile.TemporaryDirectory() as d:
        runner = AgentRunner(MockBridge([]), data_dir=d)
        erg = runner.termin_abschliessen("")
        assert erg["ok"] is False


def t_runner_keine_offenen_termine():
    with tempfile.TemporaryDirectory() as d:
        runner = AgentRunner(MockBridge([_antwort("X")]), data_dir=d)  # kein Termin
        erg = runner.termin_abschliessen("X")
        assert erg["ok"] is False
        assert "keine offenen" in erg["meldung"].lower()


# ─── Detail-Berichte ─────────────────────────────────────────────────────────

def t_termin_detail_zeigt_kontext():
    a = [_antwort("artundweise.de", termin=True, grund="positive_reply",
                  von="we@artundweise.de", postfach="emilio.allegro@rebellsystem.de",
                  gesendet="2026-04-27T23:49:09")]
    t = termin_detail_bericht(a)
    assert "we@artundweise.de" in t
    assert "27.04.2026" in t           # Datum hübsch formatiert
    assert "emilio.allegro@rebellsystem.de" in t
    assert "abschließen" in t.lower()  # Hinweis auf Abschluss-Befehl


def t_termin_detail_leer():
    assert "keine Termin" in termin_detail_bericht([])


def t_termin_detail_blendet_erledigt_aus():
    a = [_antwort("X", termin=True)]
    a[0]["erledigt"] = True
    assert "keine Termin" in termin_detail_bericht(a)


def t_antwort_detail_echte_zuerst():
    a = [_antwort("Auto GmbH", auto=True),
         _antwort("Echt GmbH", termin=True, grund="g")]
    t = antwort_detail_bericht(a)
    # Echte Antwort steht vor der Auto-Antwort
    assert t.index("Echt GmbH") < t.index("Auto GmbH")
    assert "automatische Antwort" in t


def t_antwort_detail_leer():
    assert "Noch keine Antworten" in antwort_detail_bericht([])


if __name__ == "__main__":
    print("\n=== Termin abschließen + Detail-Berichte ===\n")
    test("Speicher: neu + persistent", t_speicher_neu_und_persistent)
    test("Speicher: leerer Key", t_speicher_leerer_key)
    test("Speicher: wieder öffnen", t_speicher_wieder_oeffnen)
    test("Speicher: kaputte Datei robust", t_kaputte_datei_robust)
    test("Runner: Termin abschließen (Firma)", t_runner_termin_abschliessen)
    test("Runner: abschließen per entry_key", t_runner_abschliessen_per_key)
    test("Runner: nicht gefunden nennt offene", t_runner_abschliessen_nicht_gefunden)
    test("Runner: mehrdeutig → nachfragen", t_runner_abschliessen_mehrdeutig)
    test("Runner: leerer Suchtext", t_runner_abschliessen_leer)
    test("Runner: keine offenen Termine", t_runner_keine_offenen_termine)
    test("Detail: Termin zeigt Kontext", t_termin_detail_zeigt_kontext)
    test("Detail: Termin leer", t_termin_detail_leer)
    test("Detail: erledigt ausgeblendet", t_termin_detail_blendet_erledigt_aus)
    test("Detail: echte vor Auto-Antworten", t_antwort_detail_echte_zuerst)
    test("Detail: Antworten leer", t_antwort_detail_leer)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
