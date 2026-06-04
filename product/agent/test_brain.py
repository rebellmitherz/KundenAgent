"""Tests für Phase A.2 — Agent-Loop (brain.py).

Läuft OHNE API-Key. Claude wird über eine gemockte llm_fn simuliert;
die Engine über eine fortschreitende SimulierteEngine (kein mine.py).

Aufruf: PYTHONUTF8=1 python product/agent/test_brain.py

Abgedeckte Szenarien (HANDOFF A.4):
  - DeterministischePolitik: alle 5 Entscheidungswege
  - ClaudePolitik: valides JSON, kein Key→Fallback, kaputtes JSON→Fallback,
    gesperrtes Werkzeug→Fallback, mensch_fragen, JSON in Fließtext
  - Brain-Loop: Ziel erreicht→Mensch-Tor, Lücke→Auffüllung→Erschöpfung→Aufgeben,
    Ziel sofort erreicht (kein Suchen), Schritt-Limit greift,
    Guardrail Sende-Werkzeug→Mensch-Tor, Guardrail unbekannt→Aufgeben,
    Fehler→ehrlich Aufgeben, Speicher wird befüllt, kundentext ehrlich
"""
from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.agent.brain import (
    Aktionstyp,
    Brain,
    ClaudePolitik,
    DeterministischePolitik,
    Entscheidung,
    Lage,
    Laufergebnis,
    Schritt,
    baue_brain,
)
from product.agent.tools import AgentKontext
from product.operator.order_schema import Auftrag


# ─── Mocks ───────────────────────────────────────────────────────────────────


@dataclass
class MockBrueckenErgebnis:
    ok: bool
    leads_gefunden: int = 0
    leads_sauber: int = 0
    meldung: str = ""
    rohdaten: dict = field(default_factory=dict)


class SimulierteEngine:
    """Fortschreitende Engine: jeder suchen()-Aufruf addiert den nächsten
    geplanten Zuwachs. status_lesen() spiegelt den kumulativen Stand.

    plan: Liste von Zuwächsen pro suchen-Aufruf (danach 0).
    start: Anfangs-Stand (z. B. Pipeline aus früherem Lauf).
    fehler_bei_suche: erste Suche wirft eine Ausnahme.
    """

    def __init__(self, plan=None, start: int = 0, fehler_bei_suche: bool = False):
        self.sendbar = start
        self._plan = list(plan or [])
        self._i = 0
        self._fehler = fehler_bei_suche

    def status_lesen(self) -> dict:
        return {
            "pipeline_total": self.sendbar,
            "sendable": self.sendbar,
            "approved": 0,
            "sent_total": 0,
            "already_contacted": 0,
        }

    def suchen(self, auftrag: Auftrag) -> MockBrueckenErgebnis:
        if self._fehler:
            raise RuntimeError("Engine nicht erreichbar (Test)")
        auftrag.starten()
        zuwachs = self._plan[self._i] if self._i < len(self._plan) else 0
        self._i += 1
        self.sendbar += zuwachs
        return MockBrueckenErgebnis(
            ok=True, leads_gefunden=zuwachs, leads_sauber=zuwachs
        )


class ZaehlSpeicher:
    """Speicher-Stub — zählt Aufzeichnungen (echte Persistenz = Phase A.3)."""

    def __init__(self):
        self.schritte: list = []
        self.abschluesse: list = []

    def aufzeichnen(self, auftrag, schritt, lage):
        self.schritte.append(schritt)

    def abschluss(self, auftrag, ergebnis):
        self.abschluesse.append(ergebnis)


class FestePolitik:
    """Politik, die immer dieselbe Entscheidung liefert (für Loop-Tests)."""

    def __init__(self, entscheidung: Entscheidung):
        self._e = entscheidung

    def entscheide(self, auftrag, lage, verlauf) -> Entscheidung:
        return self._e


# ─── Fixtures ────────────────────────────────────────────────────────────────


def _auftrag(zielgruppe="Handwerker", region="NRW", anzahl=100) -> Auftrag:
    a = Auftrag(zielgruppe=zielgruppe, region=region, lead_anzahl=anzahl, angebot="ERP")
    a.bestaetigen()
    return a


def _lage(**kw) -> Lage:
    basis = dict(
        ziel=100, sendbar=0, fehlend=100,
        ziel_erreicht=False, erschoepft=False, gesucht_schon=False, letzter_fehler="",
    )
    basis.update(kw)
    return Lage(**basis)


def _kontext(engine, auftrag=None) -> AgentKontext:
    return AgentKontext(auftrag=auftrag or _auftrag(), bridge=engine, reporter=None)


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


# ─── DeterministischePolitik ─────────────────────────────────────────────────

def t_det_erste_suche():
    p = DeterministischePolitik()
    e = p.entscheide(_auftrag(), _lage(gesucht_schon=False), [])
    assert e.typ == Aktionstyp.WERKZEUG
    assert e.werkzeug == "suche_starten"


def t_det_ziel_erreicht_oeffnet_tor():
    p = DeterministischePolitik()
    e = p.entscheide(_auftrag(anzahl=50), _lage(ziel=50, sendbar=55, ziel_erreicht=True, gesucht_schon=True), [])
    assert e.typ == Aktionstyp.MENSCH_FRAGEN
    assert "Freigabe" in e.begruendung


def t_det_luecke_fuellt_auf():
    p = DeterministischePolitik()
    e = p.entscheide(_auftrag(), _lage(sendbar=20, fehlend=80, gesucht_schon=True), [])
    assert e.typ == Aktionstyp.WERKZEUG
    assert e.werkzeug == "auffuellung_starten"


def t_det_erschoepft_gibt_auf():
    p = DeterministischePolitik()
    e = p.entscheide(_auftrag(), _lage(sendbar=30, fehlend=70, gesucht_schon=True, erschoepft=True), [])
    assert e.typ == Aktionstyp.AUFGEBEN
    assert "ausgeschöpft" in e.begruendung


def t_det_fehler_gibt_auf():
    p = DeterministischePolitik()
    e = p.entscheide(_auftrag(), _lage(gesucht_schon=True, letzter_fehler="Engine weg"), [])
    assert e.typ == Aktionstyp.AUFGEBEN


def t_det_ziel_vor_suche_prioritaet():
    """Pipeline schon voll (früherer Lauf): Ziel-Tor vor neuer Suche."""
    p = DeterministischePolitik()
    e = p.entscheide(_auftrag(anzahl=10), _lage(ziel=10, sendbar=12, ziel_erreicht=True, gesucht_schon=False), [])
    assert e.typ == Aktionstyp.MENSCH_FRAGEN


# ─── ClaudePolitik ───────────────────────────────────────────────────────────

def t_claude_valides_json():
    def llm(system, user):
        return '{"typ":"werkzeug","werkzeug":"suche_starten","parameter":{},"begruendung":"los"}'
    e = ClaudePolitik(llm).entscheide(_auftrag(), _lage(), [])
    assert e.typ == Aktionstyp.WERKZEUG
    assert e.werkzeug == "suche_starten"
    assert e.begruendung == "los"


def t_claude_json_in_fliesstext():
    def llm(system, user):
        return 'Klar! Hier meine Wahl:\n{"typ":"mensch_fragen","werkzeug":"","begruendung":"bereit?"}\nViele Grüße'
    e = ClaudePolitik(llm).entscheide(_auftrag(), _lage(ziel_erreicht=True), [])
    assert e.typ == Aktionstyp.MENSCH_FRAGEN
    assert e.begruendung == "bereit?"


def t_claude_kein_key_fallback():
    e = ClaudePolitik(None).entscheide(_auftrag(), _lage(gesucht_schon=False), [])
    # Fallback = deterministisch → erste Suche
    assert e.werkzeug == "suche_starten"


def t_claude_kaputtes_json_fallback():
    def llm(system, user):
        return "ich bin gar kein json, haha"
    e = ClaudePolitik(llm).entscheide(_auftrag(), _lage(gesucht_schon=False), [])
    assert e.werkzeug == "suche_starten"  # Fallback


def t_claude_ungueltiger_typ_fallback():
    def llm(system, user):
        return '{"typ":"explodieren","werkzeug":"x"}'
    e = ClaudePolitik(llm).entscheide(_auftrag(), _lage(gesucht_schon=False), [])
    assert e.werkzeug == "suche_starten"  # Fallback


def t_claude_gesperrtes_werkzeug_fallback():
    """Claude wählt ein Sende-Werkzeug → nicht in werkzeug_namen() → Fallback."""
    def llm(system, user):
        return '{"typ":"werkzeug","werkzeug":"send","parameter":{},"begruendung":"feuer frei"}'
    e = ClaudePolitik(llm).entscheide(_auftrag(), _lage(gesucht_schon=False), [])
    assert e.werkzeug == "suche_starten"  # Fallback, NICHT "send"
    assert e.werkzeug != "send"


def t_claude_unbekanntes_werkzeug_fallback():
    def llm(system, user):
        return '{"typ":"werkzeug","werkzeug":"raketenstart"}'
    e = ClaudePolitik(llm).entscheide(_auftrag(), _lage(gesucht_schon=False), [])
    assert e.werkzeug == "suche_starten"


def t_claude_llm_ausnahme_fallback():
    def llm(system, user):
        raise RuntimeError("API down")
    e = ClaudePolitik(llm).entscheide(_auftrag(), _lage(gesucht_schon=False), [])
    assert e.werkzeug == "suche_starten"


def t_claude_prompt_enthaelt_werkzeuge_und_lage():
    erfasst = {}
    def llm(system, user):
        erfasst["system"] = system
        erfasst["user"] = user
        return '{"typ":"werkzeug","werkzeug":"suche_starten"}'
    ClaudePolitik(llm).entscheide(_auftrag(anzahl=200), _lage(ziel=200, sendbar=40, fehlend=160, gesucht_schon=True), [])
    assert "suche_starten" in erfasst["system"]
    assert "NIEMALS selbst" in erfasst["system"]
    assert "40 von 200" in erfasst["user"]


# ─── Brain-Loop (Integration) ────────────────────────────────────────────────

def t_loop_suche_dann_ziel_tor():
    """Erster Lauf: Suche bringt das Ziel → hartes Tor (Mensch)."""
    engine = SimulierteEngine(plan=[30], start=0)
    brain = Brain(_kontext(engine, _auftrag(anzahl=25)))
    erg = brain.fuehre_aus()
    assert erg.abschluss.typ == Aktionstyp.MENSCH_FRAGEN
    assert erg.menschliches_tor
    namen = [s.werkzeug for s in erg.schritte]
    assert namen == ["suche_starten"]
    assert erg.lage.sendbar >= 25


def t_loop_luecke_auffuellung_erschoepft_aufgeben():
    """Suche bringt wenig, Auffüllung erschöpft → ehrlich aufgeben."""
    engine = SimulierteEngine(plan=[20], start=0)  # danach alles 0
    brain = Brain(_kontext(engine, _auftrag(anzahl=1000)))
    erg = brain.fuehre_aus()
    assert erg.abschluss.typ == Aktionstyp.AUFGEBEN
    namen = [s.werkzeug for s in erg.schritte]
    assert namen[0] == "suche_starten"
    assert "auffuellung_starten" in namen
    assert "ausgeschöpft" in erg.abschluss.begruendung


def t_loop_ziel_sofort_kein_suchen():
    """Pipeline schon voll genug → sofort Mensch-Tor, keine Suche."""
    engine = SimulierteEngine(plan=[], start=80)
    brain = Brain(_kontext(engine, _auftrag(anzahl=50)))
    erg = brain.fuehre_aus()
    assert erg.abschluss.typ == Aktionstyp.MENSCH_FRAGEN
    assert erg.schritte == []  # kein einziger Werkzeug-Schritt nötig


def t_loop_schrittlimit_greift():
    """Politik die nie terminal wird → Limit stoppt sauber."""
    engine = SimulierteEngine(plan=[], start=0)
    immer_status = FestePolitik(Entscheidung(Aktionstyp.WERKZEUG, "status_lesen", {}, "schaue"))
    brain = Brain(_kontext(engine), politik=immer_status, max_schritte=4)
    erg = brain.fuehre_aus()
    assert erg.abschluss.typ == Aktionstyp.AUFGEBEN
    assert len(erg.schritte) == 4
    assert "Obergrenze" in erg.abschluss.begruendung


def t_loop_guardrail_sende_werkzeug():
    """Politik will senden → Guardrail wandelt in Mensch-Tor, kein Ausführen."""
    engine = SimulierteEngine(plan=[], start=0)
    sende = FestePolitik(Entscheidung(Aktionstyp.WERKZEUG, "freigabe_ausfuehren", {}, "feuer"))
    brain = Brain(_kontext(engine), politik=sende)
    erg = brain.fuehre_aus()
    assert erg.abschluss.typ == Aktionstyp.MENSCH_FRAGEN
    assert erg.schritte == []  # nichts wurde ausgeführt


def t_loop_guardrail_unbekanntes_werkzeug():
    engine = SimulierteEngine(plan=[], start=0)
    quatsch = FestePolitik(Entscheidung(Aktionstyp.WERKZEUG, "raketenstart", {}, "zoom"))
    brain = Brain(_kontext(engine), politik=quatsch)
    erg = brain.fuehre_aus()
    assert erg.abschluss.typ == Aktionstyp.AUFGEBEN
    assert erg.schritte == []


def t_loop_fehler_bei_suche_aufgeben():
    """Suche wirft → Lage.letzter_fehler → deterministisch ehrlich aufgeben."""
    engine = SimulierteEngine(fehler_bei_suche=True)
    brain = Brain(_kontext(engine, _auftrag(anzahl=100)))
    erg = brain.fuehre_aus()
    assert erg.abschluss.typ == Aktionstyp.AUFGEBEN
    # Genau ein (fehlgeschlagener) Such-Schritt, dann Stop
    assert [s.werkzeug for s in erg.schritte] == ["suche_starten"]
    assert not erg.schritte[0].ergebnis.erfolg


def t_loop_speicher_wird_befuellt():
    engine = SimulierteEngine(plan=[30], start=0)
    speicher = ZaehlSpeicher()
    brain = Brain(_kontext(engine, _auftrag(anzahl=25)), speicher=speicher)
    erg = brain.fuehre_aus()
    assert len(speicher.schritte) == len(erg.schritte) >= 1
    assert len(speicher.abschluesse) == 1


def t_loop_kundentext_ehrlich_ohne_technik():
    engine = SimulierteEngine(plan=[30], start=0)
    brain = Brain(_kontext(engine, _auftrag(anzahl=25)))
    text = brain.fuehre_aus().kundentext()
    verboten = ["mine.py", "subprocess", "Exception", "Traceback", "entry_key", "Bridge", "None"]
    for w in verboten:
        assert w not in text, f"Technik-Leak im Kundentext: {w!r}"
    assert "Entscheidung ist gefragt" in text


def t_baue_brain_ohne_key_laeuft():
    """Komfort-Factory ohne Key → ClaudePolitik nutzt deterministischen Fallback."""
    engine = SimulierteEngine(plan=[30], start=0)
    brain = baue_brain(_kontext(engine, _auftrag(anzahl=25)), api_key=None)
    erg = brain.fuehre_aus()
    assert erg.abschluss.typ == Aktionstyp.MENSCH_FRAGEN


def t_loop_claude_steuert_durchlauf():
    """Claude (gemockt) steuert den ganzen Loop bis zum Tor."""
    def llm(system, user):
        # Solange Lücke: auffüllen; bei 'ja' in Ziel-Erreicht-Hinweis: Mensch fragen.
        if "es fehlen 0" in user.lower() or "Auffüllung ausgereizt: ja" in user:
            return '{"typ":"mensch_fragen","werkzeug":"","begruendung":"bereit zur Freigabe"}'
        if "schon gesucht: nein" in user:
            return '{"typ":"werkzeug","werkzeug":"suche_starten","begruendung":"ich suche"}'
        return '{"typ":"werkzeug","werkzeug":"auffuellung_starten","begruendung":"ich fülle auf"}'
    engine = SimulierteEngine(plan=[20, 40], start=0)  # Suche 20, Auffüllung +40 → 60
    brain = Brain(_kontext(engine, _auftrag(anzahl=50)), politik=ClaudePolitik(llm))
    erg = brain.fuehre_aus()
    assert erg.abschluss.typ == Aktionstyp.MENSCH_FRAGEN
    assert erg.lage.sendbar >= 50


# ─── Haupt-Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n=== Phase A.2 — Agent-Loop (brain.py) ===\n")

    print("── DeterministischePolitik ──")
    test("erste Suche bei leerer Pipeline", t_det_erste_suche)
    test("Ziel erreicht → Mensch-Tor", t_det_ziel_erreicht_oeffnet_tor)
    test("Lücke → Auffüllung", t_det_luecke_fuellt_auf)
    test("erschöpft → Aufgeben (ehrlich)", t_det_erschoepft_gibt_auf)
    test("Fehler → Aufgeben", t_det_fehler_gibt_auf)
    test("Ziel-Tor hat Vorrang vor neuer Suche", t_det_ziel_vor_suche_prioritaet)

    print("\n── ClaudePolitik ──")
    test("valides JSON", t_claude_valides_json)
    test("JSON in Fließtext", t_claude_json_in_fliesstext)
    test("kein Key → Fallback", t_claude_kein_key_fallback)
    test("kaputtes JSON → Fallback", t_claude_kaputtes_json_fallback)
    test("ungültiger typ → Fallback", t_claude_ungueltiger_typ_fallback)
    test("gesperrtes Werkzeug → Fallback (nie send)", t_claude_gesperrtes_werkzeug_fallback)
    test("unbekanntes Werkzeug → Fallback", t_claude_unbekanntes_werkzeug_fallback)
    test("llm-Ausnahme → Fallback", t_claude_llm_ausnahme_fallback)
    test("Prompt enthält Werkzeuge + Lage", t_claude_prompt_enthaelt_werkzeuge_und_lage)

    print("\n── Brain-Loop (Integration) ──")
    test("Suche → Ziel → Mensch-Tor", t_loop_suche_dann_ziel_tor)
    test("Lücke → Auffüllung → Erschöpfung → Aufgeben", t_loop_luecke_auffuellung_erschoepft_aufgeben)
    test("Ziel sofort erreicht → kein Suchen", t_loop_ziel_sofort_kein_suchen)
    test("Schritt-Limit greift", t_loop_schrittlimit_greift)
    test("Guardrail: Sende-Werkzeug → Mensch-Tor", t_loop_guardrail_sende_werkzeug)
    test("Guardrail: unbekanntes Werkzeug → Aufgeben", t_loop_guardrail_unbekanntes_werkzeug)
    test("Fehler bei Suche → ehrlich Aufgeben", t_loop_fehler_bei_suche_aufgeben)
    test("Speicher wird befüllt", t_loop_speicher_wird_befuellt)
    test("kundentext ehrlich, ohne Technik", t_loop_kundentext_ehrlich_ohne_technik)
    test("baue_brain ohne Key läuft", t_baue_brain_ohne_key_laeuft)
    test("Claude steuert ganzen Durchlauf", t_loop_claude_steuert_durchlauf)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
