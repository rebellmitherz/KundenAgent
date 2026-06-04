"""Agent-Werkzeuge — Bridge-Aktionen als strukturierte Tool-Definitionen.

Jedes Werkzeug kapselt eine klar definierte Aktion:
  - name:             Bezeichner (snake_case) — Claude wählt per Name
  - beschreibung:     natürlichsprachig für Claude's Reasoning
  - parameter_schema: JSON-Schema (Claude-tool-use-Format)
  - ausfuehren():     (AgentKontext, dict) → WerkzeugErgebnis

V1 — NUR LESEN + SUCHEN. Senden ist kein Werkzeug hier — das bleibt
immer hartes menschliches Tor (UI-POST + Bestätigung).

Sicherheitsnachweis: SENDE_WERKZEUGE_GESPERRT listet alle verbotenen Namen;
brain.py prüft jeden Aufruf gegen diese Menge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from product.operator.expansion_maps import region_erweiterungen, verwandte_branchen
from product.operator.order_schema import (
    Auftrag,
    AuftragsStatus,
    ErlaubteAktion,
    Qualitaetskriterien,
)
from product.operator.target_fill import TargetFillManager


# Namen, die ein Agent niemals als Werkzeug wählen darf.
# brain.py erzwingt das technisch — kein Verlass auf Prompt.
SENDE_WERKZEUGE_GESPERRT: frozenset[str] = frozenset(
    {"freigabe_ausfuehren", "senden", "approve", "send", "crm_push", "auto_reply"}
)


# ─── Datenstrukturen ─────────────────────────────────────────────────────────


@dataclass
class AgentKontext:
    """Laufzeit-Kontext des Agenten — alle Abhängigkeiten gebündelt.

    bridge und reporter sind optional, damit Tests ohne echte Engine laufen.
    """
    auftrag: Auftrag
    bridge: Optional[Any] = None    # EngineBridge oder Test-Mock
    reporter: Optional[Any] = None  # Reporter oder Test-Mock

    def bridge_verfuegbar(self) -> bool:
        return self.bridge is not None

    def reporter_verfuegbar(self) -> bool:
        return self.reporter is not None


@dataclass
class WerkzeugErgebnis:
    """Ergebnis einer Werkzeug-Ausführung.

    daten:           strukturierte Fakten für den nächsten Reasoning-Schritt
    zusammenfassung: kundenfähiger Text — Claude liest diesen als Kontext
    fehler:          leer bei Erfolg, sonst technische Fehlermeldung
    """
    erfolg: bool
    daten: dict
    zusammenfassung: str
    fehler: str = ""


AusfuehrFn = Callable[[AgentKontext, dict], WerkzeugErgebnis]


@dataclass
class Werkzeug:
    """Eine deklarierte Agent-Aktion."""
    name: str
    beschreibung: str
    parameter_schema: dict
    ausfuehren: AusfuehrFn


# ─── Tool-Implementierungen ──────────────────────────────────────────────────


def _status_lesen(kontext: AgentKontext, _params: dict) -> WerkzeugErgebnis:
    if not kontext.bridge_verfuegbar():
        return WerkzeugErgebnis(
            erfolg=False,
            daten={},
            zusammenfassung="Keine Bridge verfügbar — Status kann nicht gelesen werden.",
            fehler="bridge=None",
        )
    try:
        st = kontext.bridge.status_lesen()
        zusammenfassung = (
            f"Pipeline: {st.get('pipeline_total', 0)} Einträge gesamt, "
            f"{st.get('sendable', 0)} sendbar, "
            f"{st.get('sent_total', 0)} bereits gesendet."
        )
        return WerkzeugErgebnis(erfolg=True, daten=st, zusammenfassung=zusammenfassung)
    except Exception as exc:
        return WerkzeugErgebnis(
            erfolg=False, daten={}, zusammenfassung=str(exc), fehler=str(exc)
        )


def _leads_ansehen(kontext: AgentKontext, params: dict) -> WerkzeugErgebnis:
    if not kontext.bridge_verfuegbar():
        return WerkzeugErgebnis(
            erfolg=False,
            daten={"leads": []},
            zusammenfassung="Keine Bridge verfügbar.",
            fehler="bridge=None",
        )
    limit = int(params.get("limit", 20))
    try:
        leads = kontext.bridge.leads_lesen(limit=limit)
        firmen = [lx.get("firma", "?") for lx in leads[:5]]
        mehr = f" … +{len(leads) - 5} weitere" if len(leads) > 5 else ""
        zusammenfassung = (
            f"{len(leads)} Leads geladen: {', '.join(firmen)}{mehr}."
            if leads
            else "Noch keine Leads in der Pipeline."
        )
        return WerkzeugErgebnis(
            erfolg=True, daten={"leads": leads}, zusammenfassung=zusammenfassung
        )
    except Exception as exc:
        return WerkzeugErgebnis(
            erfolg=False, daten={"leads": []}, zusammenfassung=str(exc), fehler=str(exc)
        )


def _bericht_lesen(kontext: AgentKontext, _params: dict) -> WerkzeugErgebnis:
    # Reporter bevorzugen — gibt vollständigen Strukturbericht
    if kontext.reporter_verfuegbar():
        try:
            bericht = kontext.reporter.strukturiert(kontext.auftrag)
            sendbar = bericht.get("pipeline_sendbar", 0)
            ziel = bericht.get("ziel", kontext.auftrag.lead_anzahl)
            fehlend = bericht.get("fehlend", max(0, ziel - sendbar))
            ziel_erreicht = bericht.get("ziel_erreicht", False)
            vorschlaege = bericht.get("vorschlaege", [])

            if ziel_erreicht:
                zusammenfassung = (
                    f"Ziel erreicht: {sendbar}/{ziel} saubere Leads bereit."
                )
            else:
                vs = (", ".join(vorschlaege[:2])) if vorschlaege else "keine"
                zusammenfassung = (
                    f"Ziel: {ziel}, sendbar: {sendbar}, fehlend: {fehlend}. "
                    f"Vorschläge: {vs}."
                )
            return WerkzeugErgebnis(
                erfolg=True, daten=bericht, zusammenfassung=zusammenfassung
            )
        except Exception as exc:
            return WerkzeugErgebnis(
                erfolg=False, daten={}, zusammenfassung=str(exc), fehler=str(exc)
            )

    # Fallback: nur Bridge-Status nutzen
    if kontext.bridge_verfuegbar():
        try:
            st = kontext.bridge.status_lesen()
            sendbar = st.get("sendable", 0)
            ziel = kontext.auftrag.lead_anzahl
            fehlend = max(0, ziel - sendbar)
            zusammenfassung = (
                f"Ziel: {ziel} Leads. Sendbar: {sendbar}. Fehlend: {fehlend}."
            )
            return WerkzeugErgebnis(
                erfolg=True, daten=st, zusammenfassung=zusammenfassung
            )
        except Exception as exc:
            return WerkzeugErgebnis(
                erfolg=False, daten={}, zusammenfassung=str(exc), fehler=str(exc)
            )

    return WerkzeugErgebnis(
        erfolg=False,
        daten={},
        zusammenfassung="Kein Reporter und keine Bridge verfügbar.",
        fehler="reporter=None, bridge=None",
    )


def _varianten_erkunden(kontext: AgentKontext, _params: dict) -> WerkzeugErgebnis:
    """Berechnet Erweiterungsoptionen — kein Bridge-Aufruf, reine Karte."""
    auftrag = kontext.auftrag
    gebiete = region_erweiterungen(auftrag.region)
    branchen = verwandte_branchen(auftrag.zielgruppe)

    varianten: list[dict] = []
    for g in gebiete[:4]:
        varianten.append(
            {"typ": "region", "zielgruppe": auftrag.zielgruppe, "region": g}
        )
    for b in branchen[:4]:
        varianten.append(
            {"typ": "branche", "zielgruppe": b, "region": auftrag.region}
        )

    if varianten:
        zusammenfassung = (
            f"{len(varianten)} Erweiterungsoptionen verfügbar — "
            f"Regionen: {gebiete[:3]}, Branchen: {branchen[:3]}."
        )
    else:
        zusammenfassung = (
            "Keine Erweiterungsoptionen in der Karte für diese Region/Branche."
        )

    return WerkzeugErgebnis(
        erfolg=True,
        daten={"varianten": varianten, "regionen": gebiete, "branchen": branchen},
        zusammenfassung=zusammenfassung,
    )


def _suche_starten(kontext: AgentKontext, _params: dict) -> WerkzeugErgebnis:
    """Startet die initiale Suche mit dem Auftrag aus dem Kontext."""
    if not kontext.bridge_verfuegbar():
        return WerkzeugErgebnis(
            erfolg=False,
            daten={},
            zusammenfassung=(
                "Keine Bridge verfügbar — Suche kann nicht gestartet werden."
            ),
            fehler="bridge=None",
        )
    if kontext.auftrag.status != AuftragsStatus.BESTAETIGT:
        return WerkzeugErgebnis(
            erfolg=False,
            daten={},
            zusammenfassung=(
                f"Auftrag muss BESTAETIGT sein "
                f"(aktuell: {kontext.auftrag.status.value})."
            ),
            fehler="status_check_fehlgeschlagen",
        )
    try:
        ergebnis = kontext.bridge.suchen(kontext.auftrag)
        if ergebnis.ok:
            zusammenfassung = (
                f"Suche abgeschlossen: {ergebnis.leads_gefunden} gefunden, "
                f"{ergebnis.leads_sauber} sauber (sendbar)."
            )
        else:
            zusammenfassung = f"Suche fehlgeschlagen: {ergebnis.meldung[:200]}"
        return WerkzeugErgebnis(
            erfolg=ergebnis.ok,
            daten={
                "leads_gefunden": ergebnis.leads_gefunden,
                "leads_sauber": ergebnis.leads_sauber,
                "meldung": ergebnis.meldung,
            },
            zusammenfassung=zusammenfassung,
            fehler="" if ergebnis.ok else ergebnis.meldung,
        )
    except Exception as exc:
        return WerkzeugErgebnis(
            erfolg=False,
            daten={},
            zusammenfassung=f"Fehler beim Starten der Suche: {exc}",
            fehler=str(exc),
        )


def _auffuellung_starten(kontext: AgentKontext, params: dict) -> WerkzeugErgebnis:
    """Mehrrundige Auffüllung via TargetFillManager."""
    if not kontext.bridge_verfuegbar():
        return WerkzeugErgebnis(
            erfolg=False,
            daten={},
            zusammenfassung=(
                "Keine Bridge verfügbar — Auffüllung kann nicht gestartet werden."
            ),
            fehler="bridge=None",
        )
    max_runden = int(params.get("max_runden", 8))
    try:
        manager = TargetFillManager(kontext.bridge, max_runden=max_runden)
        bericht = manager.fuelle(kontext.auftrag)
        text = TargetFillManager.bericht_text(bericht)
        return WerkzeugErgebnis(
            erfolg=True,
            daten={
                "ziel": bericht.ziel,
                "start_sendbar": bericht.start_sendbar,
                "end_sendbar": bericht.end_sendbar,
                "gewonnen": bericht.gewonnen,
                "fehlend": bericht.fehlend,
                "ziel_erreicht": bericht.ziel_erreicht,
                "abbruch_grund": bericht.abbruch_grund.value,
                "runden": len(bericht.runden),
            },
            zusammenfassung=text,
        )
    except Exception as exc:
        return WerkzeugErgebnis(
            erfolg=False,
            daten={},
            zusammenfassung=f"Fehler bei der Auffüllung: {exc}",
            fehler=str(exc),
        )


def _vorschau_lesen(kontext: AgentKontext, params: dict) -> WerkzeugErgebnis:
    """Liest Mail-Vorschau (V2) — kein Senden, nur Anzeigen."""
    if not kontext.bridge_verfuegbar():
        return WerkzeugErgebnis(
            erfolg=False,
            daten={"mails": []},
            zusammenfassung="Keine Bridge verfügbar.",
            fehler="bridge=None",
        )
    limit = int(params.get("limit", 10))
    try:
        mails = kontext.bridge.vorschau_lesen(limit=limit)
        if mails:
            firmen = [m.get("firma", "?") for m in mails[:3]]
            zusammenfassung = (
                f"{len(mails)} Mail-Entwürfe bereit "
                f"(z. B. {', '.join(firmen)}). "
                "Freigabe erfordert immer menschliche Bestätigung."
            )
        else:
            zusammenfassung = "Keine sendablen Mail-Entwürfe vorhanden."
        return WerkzeugErgebnis(
            erfolg=True,
            daten={"mails": mails, "anzahl": len(mails)},
            zusammenfassung=zusammenfassung,
        )
    except Exception as exc:
        return WerkzeugErgebnis(
            erfolg=False,
            daten={"mails": []},
            zusammenfassung=str(exc),
            fehler=str(exc),
        )


# ─── Werkzeug-Registrierung ──────────────────────────────────────────────────


def alle_werkzeuge() -> list[Werkzeug]:
    """Gibt die vollständige V1-Werkzeug-Liste zurück.

    Invariante: kein Eintrag in SENDE_WERKZEUGE_GESPERRT darf hier erscheinen.
    """
    werkzeuge = [
        Werkzeug(
            name="status_lesen",
            beschreibung=(
                "Liest den aktuellen Stand der Lead-Pipeline: "
                "Gesamtanzahl, sendbare Leads und bereits Gesendete."
            ),
            parameter_schema={"type": "object", "properties": {}, "required": []},
            ausfuehren=_status_lesen,
        ),
        Werkzeug(
            name="leads_ansehen",
            beschreibung=(
                "Zeigt die aufbereitete Lead-Liste (Firmenname, E-Mail, Telefon, Ort). "
                "Keine Rohdaten, keine Engine-Interna."
            ),
            parameter_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximale Anzahl Leads (Standard: 20)",
                        "default": 20,
                    }
                },
                "required": [],
            },
            ausfuehren=_leads_ansehen,
        ),
        Werkzeug(
            name="bericht_lesen",
            beschreibung=(
                "Erstellt einen vollständigen Fortschrittsbericht: "
                "Ziel vs. Ist, Qualitätszahlen, Lücken und konkrete Vorschläge. "
                "Ausgangspunkt für jede Entscheidung des Agenten."
            ),
            parameter_schema={"type": "object", "properties": {}, "required": []},
            ausfuehren=_bericht_lesen,
        ),
        Werkzeug(
            name="varianten_erkunden",
            beschreibung=(
                "Erkundet mögliche Erweiterungsoptionen für die aktuelle Suche: "
                "angrenzende Regionen und verwandte Branchen. "
                "Reine Berechnung — kein Bridge-Aufruf, sofort verfügbar."
            ),
            parameter_schema={"type": "object", "properties": {}, "required": []},
            ausfuehren=_varianten_erkunden,
        ),
        Werkzeug(
            name="suche_starten",
            beschreibung=(
                "Startet die initiale Lead-Suche mit dem bestätigten Auftrag. "
                "Kein Versand. Führt die Engine aus (Laufzeit: Minuten)."
            ),
            parameter_schema={"type": "object", "properties": {}, "required": []},
            ausfuehren=_suche_starten,
        ),
        Werkzeug(
            name="auffuellung_starten",
            beschreibung=(
                "Startet die mehrrundige Auffüllung bis zum Zielwert: "
                "sucht automatisch in angrenzenden Regionen und verwandten Branchen, "
                "bis das Ziel erreicht ist oder alle Optionen erschöpft sind. "
                "Kein Versand."
            ),
            parameter_schema={
                "type": "object",
                "properties": {
                    "max_runden": {
                        "type": "integer",
                        "description": "Maximale Suchrunden (Standard: 8)",
                        "default": 8,
                    }
                },
                "required": [],
            },
            ausfuehren=_auffuellung_starten,
        ),
        Werkzeug(
            name="vorschau_lesen",
            beschreibung=(
                "Liest die fertigen Mail-Entwürfe für sendbare Leads — ohne zu senden. "
                "Ermöglicht dem Kunden eine Vorschau. "
                "Das Senden selbst erfordert immer menschliche Bestätigung."
            ),
            parameter_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximale Anzahl Vorschauen (Standard: 10)",
                        "default": 10,
                    }
                },
                "required": [],
            },
            ausfuehren=_vorschau_lesen,
        ),
    ]

    # Sicherheits-Invariante prüfen — verhindert versehentliche Sende-Werkzeuge
    for w in werkzeuge:
        assert w.name not in SENDE_WERKZEUGE_GESPERRT, (
            f"SICHERHEITSFEHLER: '{w.name}' ist in SENDE_WERKZEUGE_GESPERRT — "
            "darf kein Werkzeug sein."
        )

    return werkzeuge


def werkzeug_nach_name(name: str) -> Optional[Werkzeug]:
    """Sucht ein Werkzeug nach Name. None wenn nicht gefunden."""
    for w in alle_werkzeuge():
        if w.name == name:
            return w
    return None


def werkzeug_namen() -> list[str]:
    """Gibt alle erlaubten Werkzeug-Namen zurück (für brain.py-Guardrails)."""
    return [w.name for w in alle_werkzeuge()]
