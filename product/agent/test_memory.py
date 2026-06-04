"""Tests für Phase A.3 — Lauf-Speicher (memory.py).

Läuft OHNE API-Key, OHNE echte Engine. Temp-Verzeichnis statt data/.
Aufruf: PYTHONUTF8=1 python product/agent/test_memory.py

Abgedeckte Szenarien:
  - aufzeichnen: Datei + Struktur, mehrere Schritte in Reihenfolge, Funnel-Update
  - abschluss: Status-Mapping (Mensch/Fertig/Aufgeben), Abschluss-Block
  - Persistenz: neue Instanz liest denselben Stand (überlebt "Neustart")
  - Robustheit: korrupte Datei → neu, kein Crash; atomar (kein .tmp übrig)
  - Isolation: zwei Aufträge → zwei Dateien
  - Lesen: lesen()/funnel()/alle_laeufe(), unbekannt → None/leer
  - Integration: echter Brain-Lauf mit LaufSpeicher → Datei stimmt mit Lauf
  - Sichtbarkeit: keine Lead-Rohdaten (E-Mail) im Speicher
"""
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.agent.brain import (
    Aktionstyp,
    Brain,
    Entscheidung,
    Lage,
    Laufergebnis,
    Schritt,
)
from product.agent.memory import LaufSpeicher
from product.agent.tools import AgentKontext, WerkzeugErgebnis
from product.operator.order_schema import Auftrag


# ─── Mocks / Fixtures ────────────────────────────────────────────────────────


@dataclass
class MockBrueckenErgebnis:
    ok: bool
    leads_gefunden: int = 0
    leads_sauber: int = 0
    meldung: str = ""
    rohdaten: dict = field(default_factory=dict)


class SimulierteEngine:
    def __init__(self, plan=None, start: int = 0):
        self.sendbar = start
        self._plan = list(plan or [])
        self._i = 0

    def status_lesen(self) -> dict:
        return {"pipeline_total": self.sendbar, "sendable": self.sendbar,
                "approved": 0, "sent_total": 0, "already_contacted": 0}

    def suchen(self, auftrag: Auftrag) -> MockBrueckenErgebnis:
        auftrag.starten()
        z = self._plan[self._i] if self._i < len(self._plan) else 0
        self._i += 1
        self.sendbar += z
        return MockBrueckenErgebnis(ok=True, leads_gefunden=z, leads_sauber=z)


def _auftrag(zielgruppe="Handwerker", region="NRW", anzahl=100) -> Auftrag:
    a = Auftrag(zielgruppe=zielgruppe, region=region, lead_anzahl=anzahl, angebot="ERP")
    a.bestaetigen()
    return a


def _lage(**kw) -> Lage:
    basis = dict(ziel=100, sendbar=20, fehlend=80, ziel_erreicht=False,
                 erschoepft=False, gesucht_schon=True, letzter_fehler="")
    basis.update(kw)
    return Lage(**basis)


def _schritt(nummer=1, werkzeug="suche_starten", typ=Aktionstyp.WERKZEUG,
             erfolg=True, zusammenfassung="ok", fehler="") -> Schritt:
    erg = WerkzeugErgebnis(erfolg=erfolg, daten={}, zusammenfassung=zusammenfassung, fehler=fehler)
    ent = Entscheidung(typ, werkzeug, {}, "weil")
    return Schritt(nummer=nummer, entscheidung=ent, ergebnis=erg)


def _laufergebnis(auftrag, abschluss_typ=Aktionstyp.MENSCH_FRAGEN, lage=None) -> Laufergebnis:
    return Laufergebnis(
        auftrag=auftrag,
        schritte=[],
        abschluss=Entscheidung(abschluss_typ, begruendung="fertig soweit"),
        lage=lage or _lage(),
    )


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


# ─── aufzeichnen ─────────────────────────────────────────────────────────────

def t_aufzeichnen_erstellt_datei(d):
    sp = LaufSpeicher(d)
    a = _auftrag()
    sp.aufzeichnen(a, _schritt(), _lage())
    pfad = d / "agent" / f"{a.auftrags_id}.json"
    assert pfad.exists()
    rec = json.loads(pfad.read_text(encoding="utf-8"))
    assert rec["auftrags_id"] == a.auftrags_id
    assert rec["auftrag"]["zielgruppe"] == "Handwerker"
    assert len(rec["schritte"]) == 1
    assert rec["status"] == "laeuft"


def t_aufzeichnen_mehrere_in_reihenfolge(d):
    sp = LaufSpeicher(d)
    a = _auftrag()
    sp.aufzeichnen(a, _schritt(1, "suche_starten"), _lage(sendbar=20))
    sp.aufzeichnen(a, _schritt(2, "auffuellung_starten"), _lage(sendbar=60, fehlend=40))
    rec = sp.lesen(a.auftrags_id)
    assert [s["nummer"] for s in rec["schritte"]] == [1, 2]
    assert [s["werkzeug"] for s in rec["schritte"]] == ["suche_starten", "auffuellung_starten"]
    # Funnel = letzter Stand
    assert rec["funnel"]["sendbar"] == 60
    assert rec["funnel"]["fehlend"] == 40


def t_aufzeichnen_funnel_felder(d):
    sp = LaufSpeicher(d)
    a = _auftrag(anzahl=200)
    sp.aufzeichnen(a, _schritt(), _lage(ziel=200, sendbar=50, fehlend=150, erschoepft=True))
    f = sp.funnel(a.auftrags_id)
    assert f == {"ziel": 200, "sendbar": 50, "fehlend": 150,
                 "ziel_erreicht": False, "erschoepft": True, "gesucht_schon": True}


def t_aufzeichnen_fehler_nur_wenn_vorhanden(d):
    sp = LaufSpeicher(d)
    a = _auftrag()
    sp.aufzeichnen(a, _schritt(erfolg=True, fehler=""), _lage())
    sp.aufzeichnen(a, _schritt(2, erfolg=False, fehler="Engine weg"), _lage())
    rec = sp.lesen(a.auftrags_id)
    assert "fehler" not in rec["schritte"][0]
    assert rec["schritte"][1]["fehler"] == "Engine weg"


# ─── abschluss ───────────────────────────────────────────────────────────────

def t_abschluss_mensch_tor_status(d):
    sp = LaufSpeicher(d)
    a = _auftrag()
    sp.abschluss(a, _laufergebnis(a, Aktionstyp.MENSCH_FRAGEN))
    rec = sp.lesen(a.auftrags_id)
    assert rec["status"] == "wartet_auf_mensch"
    assert rec["abschluss"]["typ"] == "mensch_fragen"
    assert rec["abschluss"]["begruendung"] == "fertig soweit"
    assert rec["abschluss"]["zeitstempel"]


def t_abschluss_fertig_status(d):
    sp = LaufSpeicher(d)
    a = _auftrag()
    sp.abschluss(a, _laufergebnis(a, Aktionstyp.FERTIG))
    assert sp.lesen(a.auftrags_id)["status"] == "abgeschlossen"


def t_abschluss_aufgeben_status(d):
    sp = LaufSpeicher(d)
    a = _auftrag()
    sp.abschluss(a, _laufergebnis(a, Aktionstyp.AUFGEBEN))
    assert sp.lesen(a.auftrags_id)["status"] == "aufgegeben"


def t_abschluss_nach_schritten_behaelt_schritte(d):
    sp = LaufSpeicher(d)
    a = _auftrag()
    sp.aufzeichnen(a, _schritt(1), _lage())
    sp.abschluss(a, _laufergebnis(a, Aktionstyp.MENSCH_FRAGEN, lage=_lage(sendbar=99)))
    rec = sp.lesen(a.auftrags_id)
    assert len(rec["schritte"]) == 1           # Schritt bleibt erhalten
    assert rec["funnel"]["sendbar"] == 99      # Funnel auf finalen Stand
    assert rec["abschluss"] is not None


# ─── Persistenz / Robustheit ────────────────────────────────────────────────

def t_persistenz_neue_instanz_liest(d):
    a = _auftrag()
    sp1 = LaufSpeicher(d)
    sp1.aufzeichnen(a, _schritt(1), _lage(sendbar=42))
    # "Neustart": frische Instanz, gleicher Ordner
    sp2 = LaufSpeicher(d)
    rec = sp2.lesen(a.auftrags_id)
    assert rec is not None
    assert rec["funnel"]["sendbar"] == 42


def t_korrupte_datei_neu_kein_crash(d):
    sp = LaufSpeicher(d)
    a = _auftrag()
    pfad = d / "agent" / f"{a.auftrags_id}.json"
    pfad.write_text("{kaputt kaputt", encoding="utf-8")
    # aufzeichnen darf nicht abstürzen, sondern sauber neu beginnen
    sp.aufzeichnen(a, _schritt(1), _lage())
    rec = sp.lesen(a.auftrags_id)
    assert rec is not None
    assert len(rec["schritte"]) == 1


def t_atomar_kein_tmp_uebrig(d):
    sp = LaufSpeicher(d)
    a = _auftrag()
    sp.aufzeichnen(a, _schritt(), _lage())
    sp.abschluss(a, _laufergebnis(a))
    tmp_dateien = list((d / "agent").glob("*.tmp"))
    assert tmp_dateien == []


def t_zwei_auftraege_isoliert(d):
    sp = LaufSpeicher(d)
    a = _auftrag("Handwerker", "NRW")
    b = _auftrag("Dachdecker", "Bayern")
    sp.aufzeichnen(a, _schritt(1), _lage(sendbar=10))
    sp.aufzeichnen(b, _schritt(1), _lage(sendbar=99))
    assert sp.funnel(a.auftrags_id)["sendbar"] == 10
    assert sp.funnel(b.auftrags_id)["sendbar"] == 99
    assert a.auftrags_id != b.auftrags_id


# ─── Lesen ───────────────────────────────────────────────────────────────────

def t_lesen_unbekannt_none(d):
    sp = LaufSpeicher(d)
    assert sp.lesen("gibt_es_nicht") is None
    assert sp.funnel("gibt_es_nicht") == {}


def t_alle_laeufe_uebersicht(d):
    sp = LaufSpeicher(d)
    a = _auftrag("Handwerker", "NRW")
    b = _auftrag("Coaches", "Berlin")
    sp.aufzeichnen(a, _schritt(1), _lage())
    sp.aufzeichnen(b, _schritt(1), _lage())
    sp.abschluss(b, _laufergebnis(b, Aktionstyp.AUFGEBEN))
    laeufe = sp.alle_laeufe()
    ids = {x["auftrags_id"] for x in laeufe}
    assert ids == {a.auftrags_id, b.auftrags_id}
    eintrag_b = next(x for x in laeufe if x["auftrags_id"] == b.auftrags_id)
    assert eintrag_b["status"] == "aufgegeben"
    assert eintrag_b["schritte_anzahl"] == 1


def t_alle_laeufe_leer(d):
    sp = LaufSpeicher(d)
    assert sp.alle_laeufe() == []


def t_data_dir_wird_angelegt(d):
    unterordner = d / "tief" / "drin"
    sp = LaufSpeicher(unterordner)
    assert (unterordner / "agent").exists()


# ─── Integration mit Brain ───────────────────────────────────────────────────

def t_integration_brain_lauf(d):
    """Echter Brain-Lauf schreibt Schritte + Abschluss korrekt."""
    sp = LaufSpeicher(d)
    a = _auftrag(anzahl=25)
    engine = SimulierteEngine(plan=[30], start=0)
    kontext = AgentKontext(auftrag=a, bridge=engine, reporter=None)
    erg = Brain(kontext, speicher=sp).fuehre_aus()

    rec = sp.lesen(a.auftrags_id)
    assert rec is not None
    # Brain hat genau die ausgeführten Schritte gespeichert
    assert len(rec["schritte"]) == len(erg.schritte) == 1
    assert rec["schritte"][0]["werkzeug"] == "suche_starten"
    # Abschluss = Mensch-Tor, Funnel zeigt Ziel erreicht
    assert rec["status"] == "wartet_auf_mensch"
    assert rec["funnel"]["sendbar"] >= 25
    assert rec["funnel"]["ziel_erreicht"] is True


def t_integration_kein_lead_rohdaten(d):
    """Der Speicher darf keine Lead-PII (E-Mail) enthalten."""
    sp = LaufSpeicher(d)
    a = _auftrag(anzahl=25)
    engine = SimulierteEngine(plan=[30], start=0)
    kontext = AgentKontext(auftrag=a, bridge=engine, reporter=None)
    Brain(kontext, speicher=sp).fuehre_aus()
    roh = (d / "agent" / f"{a.auftrags_id}.json").read_text(encoding="utf-8")
    assert "@" not in roh, "Möglicher E-Mail-Leak im Lauf-Speicher"


# ─── Haupt-Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n=== Phase A.3 — Lauf-Speicher (memory.py) ===\n")

    print("── aufzeichnen ──")
    test("erstellt Datei + Struktur", t_aufzeichnen_erstellt_datei)
    test("mehrere Schritte in Reihenfolge", t_aufzeichnen_mehrere_in_reihenfolge)
    test("Funnel-Felder vollständig", t_aufzeichnen_funnel_felder)
    test("Fehler nur wenn vorhanden", t_aufzeichnen_fehler_nur_wenn_vorhanden)

    print("\n── abschluss ──")
    test("Mensch-Tor → wartet_auf_mensch", t_abschluss_mensch_tor_status)
    test("Fertig → abgeschlossen", t_abschluss_fertig_status)
    test("Aufgeben → aufgegeben", t_abschluss_aufgeben_status)
    test("behält Schritte, setzt finalen Funnel", t_abschluss_nach_schritten_behaelt_schritte)

    print("\n── Persistenz / Robustheit ──")
    test("neue Instanz liest Stand", t_persistenz_neue_instanz_liest)
    test("korrupte Datei → neu, kein Crash", t_korrupte_datei_neu_kein_crash)
    test("atomar — kein .tmp übrig", t_atomar_kein_tmp_uebrig)
    test("zwei Aufträge isoliert", t_zwei_auftraege_isoliert)

    print("\n── Lesen ──")
    test("unbekannt → None/leer", t_lesen_unbekannt_none)
    test("alle_laeufe Übersicht", t_alle_laeufe_uebersicht)
    test("alle_laeufe leer", t_alle_laeufe_leer)
    test("data_dir wird angelegt", t_data_dir_wird_angelegt)

    print("\n── Integration mit Brain ──")
    test("echter Brain-Lauf gespeichert", t_integration_brain_lauf)
    test("keine Lead-Rohdaten (PII)", t_integration_kein_lead_rohdaten)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
