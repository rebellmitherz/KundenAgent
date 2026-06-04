"""Tests für Phase A — Agent-Werkzeuge (tools.py).

Läuft OHNE API-Key und OHNE echte Engine (Bridge ist gemockt).
Aufruf: PYTHONUTF8=1 python product/agent/test_agent.py

Abgedeckte Szenarien:
  - Werkzeug-Registrierung und Sicherheits-Invarianten
  - status_lesen: Erfolg, Bridge-fehlt, Bridge-Fehler
  - leads_ansehen: volle Liste, leer, Limit, Bridge-fehlt
  - bericht_lesen: via Reporter, via Bridge-Fallback, kein Reporter
  - varianten_erkunden: NRW/Handwerker (Match), unbekannte Region
  - suche_starten: Erfolg, Fehler, kein BESTAETIGT-Status, Bridge-fehlt
  - auffuellung_starten: Erfolg, erschöpft, Bridge-fehlt
  - vorschau_lesen: vorhanden, leer, Bridge-fehlt
  - Guardrail: SENDE_WERKZEUGE_GESPERRT
"""
from __future__ import annotations

import sys
import traceback
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Projekt-Root auf sys.path setzen (Tests laufen direkt, nicht als Package)
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.agent.tools import (
    SENDE_WERKZEUGE_GESPERRT,
    AgentKontext,
    WerkzeugErgebnis,
    alle_werkzeuge,
    werkzeug_nach_name,
    werkzeug_namen,
)
from product.operator.order_schema import (
    Auftrag,
    AuftragsStatus,
    ErlaubteAktion,
    Qualitaetskriterien,
)


# ─── Mock-Klassen ────────────────────────────────────────────────────────────


@dataclass
class MockBrueckenErgebnis:
    ok: bool
    leads_gefunden: int = 0
    leads_sauber: int = 0
    meldung: str = ""
    rohdaten: dict = field(default_factory=dict)


class MockBridge:
    """Test-Doppelgänger für EngineBridge — kein mine.py-Aufruf."""

    def __init__(
        self,
        status: Optional[dict] = None,
        leads: Optional[list[dict]] = None,
        vorschau: Optional[list[dict]] = None,
        suchen_ergebnis: Optional[MockBrueckenErgebnis] = None,
        fehler_bei_suche: bool = False,
    ):
        self._status = status if status is not None else {
            "pipeline_total": 20,
            "sendable": 15,
            "approved": 0,
            "sent_total": 0,
            "already_contacted": 0,
        }
        self._leads = leads if leads is not None else [
            {"firma": f"Firma {i}", "email": f"f{i}@example.com",
             "telefon": f"0211{i:04d}", "ansprechpartner": f"Max {i}",
             "website": f"f{i}.de", "score": 70 + i, "ort": "Düsseldorf"}
            for i in range(1, 6)
        ]
        self._vorschau = vorschau if vorschau is not None else []
        self._suchen_ergebnis = suchen_ergebnis or MockBrueckenErgebnis(
            ok=True, leads_gefunden=20, leads_sauber=15, meldung="Suche abgeschlossen."
        )
        self._fehler_bei_suche = fehler_bei_suche

    def status_lesen(self) -> dict:
        return dict(self._status)

    def leads_lesen(self, limit: int = 50) -> list[dict]:
        return self._leads[:limit]

    def vorschau_lesen(self, limit: int = 30) -> list[dict]:
        return self._vorschau[:limit]

    def suchen(self, auftrag: Auftrag) -> MockBrueckenErgebnis:
        if self._fehler_bei_suche:
            raise RuntimeError("Engine nicht erreichbar (Test)")
        # Status-Transition wie echter Bridge
        auftrag.starten()
        return self._suchen_ergebnis


class MockReporter:
    """Test-Doppelgänger für Reporter."""

    def __init__(self, bericht: Optional[dict] = None):
        self._bericht = bericht or {
            "ziel": 100,
            "gefunden": 80,
            "sauber_telefon": 60,
            "hot": 20,
            "mit_ansprechpartner": 50,
            "avg_score": 72.5,
            "pipeline_sendbar": 60,
            "ziel_erreicht": False,
            "fehlend": 40,
            "zielgruppe_erschoepft": False,
            "vorschlaege": ["Regionale Erweiterung: Ruhrgebiet", "Verwandte Branchen: Dachdecker"],
            "top_leads": [],
            "auftrag": {"zielgruppe": "Handwerker", "region": "NRW", "angebot": "ERP", "lead_anzahl": 100},
        }

    def strukturiert(self, auftrag) -> dict:
        return dict(self._bericht)


# ─── Hilfs-Fixtures ──────────────────────────────────────────────────────────


def _auftrag_bestaetigt(
    zielgruppe: str = "Handwerker",
    region: str = "NRW",
    anzahl: int = 100,
) -> Auftrag:
    a = Auftrag(
        zielgruppe=zielgruppe,
        region=region,
        lead_anzahl=anzahl,
        angebot="ERP-Software",
    )
    a.bestaetigen()
    return a


def _auftrag_entwurf() -> Auftrag:
    return Auftrag(
        zielgruppe="Dachdecker",
        region="Bayern",
        lead_anzahl=50,
        angebot="Abrechnungssoftware",
    )


# ─── Test-Runner ─────────────────────────────────────────────────────────────

_ok = 0
_fail = 0


def test(name: str, fn):
    global _ok, _fail
    try:
        fn()
        print(f"  ✓  {name}")
        _ok += 1
    except Exception:
        print(f"  ✗  {name}")
        traceback.print_exc(limit=4)
        _fail += 1


# ─── Tests: Registrierung + Sicherheits-Invarianten ─────────────────────────

def t_registrierung_alle_werkzeuge_geladen():
    ws = alle_werkzeuge()
    assert len(ws) == 7, f"Erwartet 7 Werkzeuge, bekommen {len(ws)}"


def t_registrierung_namen_eindeutig():
    namen = werkzeug_namen()
    assert len(namen) == len(set(namen)), "Doppelte Werkzeug-Namen gefunden"


def t_registrierung_kein_send_werkzeug():
    namen = set(werkzeug_namen())
    verboten = namen & SENDE_WERKZEUGE_GESPERRT
    assert not verboten, f"Verbotene Werkzeuge registriert: {verboten}"


def t_registrierung_schema_vorhanden():
    for w in alle_werkzeuge():
        assert isinstance(w.parameter_schema, dict), f"{w.name}: Schema kein dict"
        assert "type" in w.parameter_schema, f"{w.name}: 'type' fehlt im Schema"


def t_werkzeug_nach_name_gefunden():
    w = werkzeug_nach_name("status_lesen")
    assert w is not None
    assert w.name == "status_lesen"


def t_werkzeug_nach_name_nicht_gefunden():
    w = werkzeug_nach_name("freigabe_ausfuehren")
    assert w is None, "Sende-Werkzeug darf nicht gefunden werden"


def t_werkzeug_nach_name_unbekannt():
    w = werkzeug_nach_name("nicht_existent_xyz")
    assert w is None


# ─── Tests: status_lesen ────────────────────────────────────────────────────

def t_status_lesen_erfolg():
    kontext = AgentKontext(auftrag=_auftrag_bestaetigt(), bridge=MockBridge())
    w = werkzeug_nach_name("status_lesen")
    ergebnis = w.ausfuehren(kontext, {})
    assert ergebnis.erfolg
    assert ergebnis.daten.get("pipeline_total") == 20
    assert ergebnis.daten.get("sendable") == 15
    assert "sendbar" in ergebnis.zusammenfassung


def t_status_lesen_ohne_bridge():
    kontext = AgentKontext(auftrag=_auftrag_bestaetigt(), bridge=None)
    w = werkzeug_nach_name("status_lesen")
    ergebnis = w.ausfuehren(kontext, {})
    assert not ergebnis.erfolg
    assert ergebnis.fehler == "bridge=None"


def t_status_lesen_bridge_fehler():
    class KaputterBridge:
        def status_lesen(self):
            raise RuntimeError("Datei fehlt")

    kontext = AgentKontext(auftrag=_auftrag_bestaetigt(), bridge=KaputterBridge())
    w = werkzeug_nach_name("status_lesen")
    ergebnis = w.ausfuehren(kontext, {})
    assert not ergebnis.erfolg
    assert "Datei fehlt" in ergebnis.fehler


# ─── Tests: leads_ansehen ───────────────────────────────────────────────────

def t_leads_ansehen_volle_liste():
    kontext = AgentKontext(auftrag=_auftrag_bestaetigt(), bridge=MockBridge())
    w = werkzeug_nach_name("leads_ansehen")
    ergebnis = w.ausfuehren(kontext, {"limit": 5})
    assert ergebnis.erfolg
    assert len(ergebnis.daten["leads"]) == 5
    assert "Leads geladen" in ergebnis.zusammenfassung


def t_leads_ansehen_leer():
    bridge = MockBridge(leads=[])
    kontext = AgentKontext(auftrag=_auftrag_bestaetigt(), bridge=bridge)
    w = werkzeug_nach_name("leads_ansehen")
    ergebnis = w.ausfuehren(kontext, {})
    assert ergebnis.erfolg
    assert ergebnis.daten["leads"] == []
    assert "keine" in ergebnis.zusammenfassung.lower()


def t_leads_ansehen_limit_greift():
    bridge = MockBridge(leads=[
        {"firma": f"F{i}", "email": "", "telefon": "", "ansprechpartner": "",
         "website": "", "score": 0, "ort": ""}
        for i in range(30)
    ])
    kontext = AgentKontext(auftrag=_auftrag_bestaetigt(), bridge=bridge)
    w = werkzeug_nach_name("leads_ansehen")
    ergebnis = w.ausfuehren(kontext, {"limit": 10})
    assert len(ergebnis.daten["leads"]) == 10


def t_leads_ansehen_ohne_bridge():
    kontext = AgentKontext(auftrag=_auftrag_bestaetigt(), bridge=None)
    w = werkzeug_nach_name("leads_ansehen")
    ergebnis = w.ausfuehren(kontext, {})
    assert not ergebnis.erfolg
    assert ergebnis.daten["leads"] == []


# ─── Tests: bericht_lesen ───────────────────────────────────────────────────

def t_bericht_lesen_mit_reporter():
    kontext = AgentKontext(
        auftrag=_auftrag_bestaetigt(),
        bridge=MockBridge(),
        reporter=MockReporter(),
    )
    w = werkzeug_nach_name("bericht_lesen")
    ergebnis = w.ausfuehren(kontext, {})
    assert ergebnis.erfolg
    assert "fehlend" in ergebnis.zusammenfassung.lower() or "ziel" in ergebnis.zusammenfassung.lower()
    assert "pipeline_sendbar" in ergebnis.daten


def t_bericht_lesen_reporter_ziel_erreicht():
    reporter = MockReporter({
        "ziel": 50, "pipeline_sendbar": 50,
        "ziel_erreicht": True, "fehlend": 0,
        "vorschlaege": [],
        "gefunden": 50, "sauber_telefon": 50, "hot": 10,
        "mit_ansprechpartner": 40, "avg_score": 80.0,
        "top_leads": [], "auftrag": {},
        "zielgruppe_erschoepft": False,
    })
    kontext = AgentKontext(
        auftrag=_auftrag_bestaetigt(anzahl=50),
        bridge=MockBridge(),
        reporter=reporter,
    )
    w = werkzeug_nach_name("bericht_lesen")
    ergebnis = w.ausfuehren(kontext, {})
    assert ergebnis.erfolg
    assert "ziel erreicht" in ergebnis.zusammenfassung.lower()


def t_bericht_lesen_fallback_bridge():
    bridge = MockBridge(status={"sendable": 30, "pipeline_total": 30})
    kontext = AgentKontext(
        auftrag=_auftrag_bestaetigt(anzahl=100),
        bridge=bridge,
        reporter=None,
    )
    w = werkzeug_nach_name("bericht_lesen")
    ergebnis = w.ausfuehren(kontext, {})
    assert ergebnis.erfolg
    assert "sendbar" in ergebnis.zusammenfassung.lower()


def t_bericht_lesen_kein_reporter_keine_bridge():
    kontext = AgentKontext(auftrag=_auftrag_bestaetigt(), bridge=None, reporter=None)
    w = werkzeug_nach_name("bericht_lesen")
    ergebnis = w.ausfuehren(kontext, {})
    assert not ergebnis.erfolg


# ─── Tests: varianten_erkunden ──────────────────────────────────────────────

def t_varianten_erkunden_nrw_handwerker():
    kontext = AgentKontext(auftrag=_auftrag_bestaetigt("Handwerker", "NRW"))
    w = werkzeug_nach_name("varianten_erkunden")
    ergebnis = w.ausfuehren(kontext, {})
    assert ergebnis.erfolg
    varianten = ergebnis.daten["varianten"]
    assert len(varianten) > 0
    typen = {v["typ"] for v in varianten}
    assert "region" in typen
    assert "branche" in typen
    regionen = ergebnis.daten["regionen"]
    assert "Ruhrgebiet" in regionen or "Münsterland" in regionen


def t_varianten_erkunden_keine_treffer():
    a = Auftrag(
        zielgruppe="Mondscheinbäcker",
        region="Atlantis",
        lead_anzahl=10,
        angebot="Luft",
    )
    a.bestaetigen()
    kontext = AgentKontext(auftrag=a)
    w = werkzeug_nach_name("varianten_erkunden")
    ergebnis = w.ausfuehren(kontext, {})
    assert ergebnis.erfolg  # Reine Berechnung — kein Fehler
    assert ergebnis.daten["varianten"] == []
    assert "keine" in ergebnis.zusammenfassung.lower()


# ─── Tests: suche_starten ───────────────────────────────────────────────────

def t_suche_starten_erfolg():
    kontext = AgentKontext(auftrag=_auftrag_bestaetigt(), bridge=MockBridge())
    w = werkzeug_nach_name("suche_starten")
    ergebnis = w.ausfuehren(kontext, {})
    assert ergebnis.erfolg
    assert ergebnis.daten["leads_gefunden"] == 20
    assert ergebnis.daten["leads_sauber"] == 15
    assert "abgeschlossen" in ergebnis.zusammenfassung.lower()


def t_suche_starten_ohne_bridge():
    kontext = AgentKontext(auftrag=_auftrag_bestaetigt(), bridge=None)
    w = werkzeug_nach_name("suche_starten")
    ergebnis = w.ausfuehren(kontext, {})
    assert not ergebnis.erfolg
    assert "bridge=None" in ergebnis.fehler


def t_suche_starten_falsche_status():
    """Auftrag im ENTWURF-Status — Bridge darf nicht aufgerufen werden."""
    kontext = AgentKontext(auftrag=_auftrag_entwurf(), bridge=MockBridge())
    w = werkzeug_nach_name("suche_starten")
    ergebnis = w.ausfuehren(kontext, {})
    assert not ergebnis.erfolg
    assert "BESTAETIGT" in ergebnis.zusammenfassung


def t_suche_starten_engine_fehler():
    bridge = MockBridge(fehler_bei_suche=True)
    kontext = AgentKontext(auftrag=_auftrag_bestaetigt(), bridge=bridge)
    w = werkzeug_nach_name("suche_starten")
    ergebnis = w.ausfuehren(kontext, {})
    assert not ergebnis.erfolg
    assert "nicht erreichbar" in ergebnis.fehler


def t_suche_starten_engine_gibt_fehler_zurueck():
    bridge = MockBridge(
        suchen_ergebnis=MockBrueckenErgebnis(
            ok=False, meldung="mine.py Lizenzfehler"
        )
    )
    kontext = AgentKontext(auftrag=_auftrag_bestaetigt(), bridge=bridge)
    w = werkzeug_nach_name("suche_starten")
    ergebnis = w.ausfuehren(kontext, {})
    assert not ergebnis.erfolg
    assert "fehlgeschlagen" in ergebnis.zusammenfassung.lower()


# ─── Tests: auffuellung_starten ────────────────────────────────────────────

def t_auffuellung_starten_ziel_erreicht():
    """TargetFillManager mockt Bridge — alle Runden bringen Zuwachs."""

    class SaettigendeBridge:
        """Simuliert: 1 Runde genügt, Ziel wird erreicht."""
        _sendbar = 0

        def status_lesen(self) -> dict:
            return {"sendable": self._sendbar}

        def suchen(self, auftrag: Auftrag) -> MockBrueckenErgebnis:
            auftrag.starten()
            SaettigendeBridge._sendbar = auftrag.lead_anzahl
            return MockBrueckenErgebnis(
                ok=True,
                leads_gefunden=auftrag.lead_anzahl,
                leads_sauber=auftrag.lead_anzahl,
            )

    kontext = AgentKontext(
        auftrag=_auftrag_bestaetigt(anzahl=10),
        bridge=SaettigendeBridge(),
    )
    w = werkzeug_nach_name("auffuellung_starten")
    ergebnis = w.ausfuehren(kontext, {"max_runden": 3})
    assert ergebnis.erfolg
    assert ergebnis.daten["ziel_erreicht"]


def t_auffuellung_starten_erschoepft():
    """Bridge gibt immer 0 Zuwachs → erschöpft nach 2 leeren Runden."""

    class LeereBridge:
        def status_lesen(self) -> dict:
            return {"sendable": 5}

        def suchen(self, auftrag: Auftrag):
            auftrag.starten()
            return MockBrueckenErgebnis(ok=True, leads_gefunden=0, leads_sauber=0)

    kontext = AgentKontext(
        auftrag=_auftrag_bestaetigt(anzahl=100),
        bridge=LeereBridge(),
    )
    w = werkzeug_nach_name("auffuellung_starten")
    ergebnis = w.ausfuehren(kontext, {"max_runden": 5})
    assert ergebnis.erfolg
    assert not ergebnis.daten["ziel_erreicht"]
    assert ergebnis.daten["fehlend"] > 0


def t_auffuellung_starten_ohne_bridge():
    kontext = AgentKontext(auftrag=_auftrag_bestaetigt(), bridge=None)
    w = werkzeug_nach_name("auffuellung_starten")
    ergebnis = w.ausfuehren(kontext, {})
    assert not ergebnis.erfolg
    assert "bridge=None" in ergebnis.fehler


# ─── Tests: vorschau_lesen ──────────────────────────────────────────────────

def t_vorschau_lesen_mit_mails():
    vorschau = [
        {"firma": "Alpha GmbH", "email": "a@alpha.de",
         "ansprechpartner": "Herr Müller", "betreff": "Test",
         "inhalt": "Hallo...", "approved": False, "entry_key": "k1"},
        {"firma": "Beta AG", "email": "b@beta.de",
         "ansprechpartner": "Frau Schmidt", "betreff": "Test2",
         "inhalt": "Hallo 2...", "approved": False, "entry_key": "k2"},
    ]
    bridge = MockBridge(vorschau=vorschau)
    kontext = AgentKontext(auftrag=_auftrag_bestaetigt(), bridge=bridge)
    w = werkzeug_nach_name("vorschau_lesen")
    ergebnis = w.ausfuehren(kontext, {})
    assert ergebnis.erfolg
    assert ergebnis.daten["anzahl"] == 2
    assert "Alpha GmbH" in ergebnis.zusammenfassung
    assert "menschliche Bestätigung" in ergebnis.zusammenfassung


def t_vorschau_lesen_leer():
    bridge = MockBridge(vorschau=[])
    kontext = AgentKontext(auftrag=_auftrag_bestaetigt(), bridge=bridge)
    w = werkzeug_nach_name("vorschau_lesen")
    ergebnis = w.ausfuehren(kontext, {})
    assert ergebnis.erfolg
    assert ergebnis.daten["anzahl"] == 0
    assert "keine" in ergebnis.zusammenfassung.lower()


def t_vorschau_lesen_ohne_bridge():
    kontext = AgentKontext(auftrag=_auftrag_bestaetigt(), bridge=None)
    w = werkzeug_nach_name("vorschau_lesen")
    ergebnis = w.ausfuehren(kontext, {})
    assert not ergebnis.erfolg
    assert "bridge=None" in ergebnis.fehler


# ─── Haupt-Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n=== Phase A.1 — Agent-Werkzeuge ===\n")

    print("── Registrierung + Sicherheits-Invarianten ──")
    test("alle 7 Werkzeuge geladen", t_registrierung_alle_werkzeuge_geladen)
    test("Namen eindeutig", t_registrierung_namen_eindeutig)
    test("kein Sende-Werkzeug registriert", t_registrierung_kein_send_werkzeug)
    test("alle Schemas vorhanden", t_registrierung_schema_vorhanden)
    test("werkzeug_nach_name findet status_lesen", t_werkzeug_nach_name_gefunden)
    test("werkzeug_nach_name: Sende-Name → None", t_werkzeug_nach_name_nicht_gefunden)
    test("werkzeug_nach_name: unbekannt → None", t_werkzeug_nach_name_unbekannt)

    print("\n── status_lesen ──")
    test("Erfolg mit Bridge", t_status_lesen_erfolg)
    test("ohne Bridge → Fehler", t_status_lesen_ohne_bridge)
    test("Bridge-Fehler → Fehler", t_status_lesen_bridge_fehler)

    print("\n── leads_ansehen ──")
    test("volle Liste", t_leads_ansehen_volle_liste)
    test("leere Pipeline", t_leads_ansehen_leer)
    test("Limit greift", t_leads_ansehen_limit_greift)
    test("ohne Bridge → Fehler", t_leads_ansehen_ohne_bridge)

    print("\n── bericht_lesen ──")
    test("mit Reporter", t_bericht_lesen_mit_reporter)
    test("Reporter: Ziel erreicht", t_bericht_lesen_reporter_ziel_erreicht)
    test("Fallback: nur Bridge", t_bericht_lesen_fallback_bridge)
    test("kein Reporter + kein Bridge → Fehler", t_bericht_lesen_kein_reporter_keine_bridge)

    print("\n── varianten_erkunden ──")
    test("NRW/Handwerker → Regionen + Branchen", t_varianten_erkunden_nrw_handwerker)
    test("unbekannte Region → leere Liste, kein Fehler", t_varianten_erkunden_keine_treffer)

    print("\n── suche_starten ──")
    test("Erfolg", t_suche_starten_erfolg)
    test("ohne Bridge → Fehler", t_suche_starten_ohne_bridge)
    test("falscher Status (ENTWURF) → Fehler", t_suche_starten_falsche_status)
    test("Engine-Ausnahme → Fehler", t_suche_starten_engine_fehler)
    test("Engine gibt ok=False zurück", t_suche_starten_engine_gibt_fehler_zurueck)

    print("\n── auffuellung_starten ──")
    test("Ziel erreicht in Runde 1", t_auffuellung_starten_ziel_erreicht)
    test("erschöpft → ehrlich stoppen", t_auffuellung_starten_erschoepft)
    test("ohne Bridge → Fehler", t_auffuellung_starten_ohne_bridge)

    print("\n── vorschau_lesen ──")
    test("Mails vorhanden", t_vorschau_lesen_mit_mails)
    test("keine Mails → leer", t_vorschau_lesen_leer)
    test("ohne Bridge → Fehler", t_vorschau_lesen_ohne_bridge)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
