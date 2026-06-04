"""Agent-Loop — das Gehirn des Hermes Sales Operator (Phase A.2).

Aus dem Operator wird ein echter Agent: Ziel rein → der Agent liest die Lage,
entscheidet die nächste Aktion, handelt, bewertet — und wiederholt, bis das Ziel
erreicht ist, die Zielgruppe ausgeschöpft ist, oder ein hartes Tor (Senden) eine
menschliche Entscheidung verlangt.

Architektur:
  observe  → bericht_lesen (aktuelle Lage)
  decide   → Politik wählt eine Entscheidung aus der erlaubten Werkzeug-Liste
  act      → Werkzeug ausführen (NUR lesen/suchen — Senden ist kein Werkzeug)
  evaluate → Lage neu lesen → weiter oder terminal

Zwei austauschbare Entscheidungs-Quellen (Politiken):
  - ClaudePolitik:         Claude ist der Reasoning-Kern (llm_anthropic).
  - DeterministischePolitik: regelbasiert — greift OHNE API-Key und als Fallback,
                             damit Tests deterministisch ohne Key laufen.

Sicherheit (HANDOFF §2):
  - Guardrail im Loop: nur Werkzeuge aus werkzeug_namen() werden ausgeführt.
  - Jeder Versuch, ein Sende-Werkzeug zu wählen, wird hart in ein menschliches
    Tor (MENSCH_FRAGEN) umgewandelt — der Agent sendet NIEMALS selbst.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol

from product.agent.tools import (
    SENDE_WERKZEUGE_GESPERRT,
    AgentKontext,
    alle_werkzeuge,
    werkzeug_nach_name,
    werkzeug_namen,
)
from product.operator.order_schema import Auftrag


# ─── Entscheidungs-Modell ────────────────────────────────────────────────────


class Aktionstyp(str, Enum):
    WERKZEUG = "werkzeug"            # ein Werkzeug ausführen
    FERTIG = "fertig"               # Ziel erreicht, nichts mehr zu tun
    MENSCH_FRAGEN = "mensch_fragen"  # hartes Tor: menschliche Entscheidung nötig
    AUFGEBEN = "aufgeben"           # ehrlich stoppen (erschöpft / Fehler / Limit)


@dataclass
class Entscheidung:
    """Eine Entscheidung der Politik — die nächste Aktion des Agenten."""
    typ: Aktionstyp
    werkzeug: str = ""
    parameter: dict = field(default_factory=dict)
    begruendung: str = ""   # ruhige, kundenfähige Erklärung — keine Technik

    def ist_terminal(self) -> bool:
        return self.typ != Aktionstyp.WERKZEUG


@dataclass
class Lage:
    """Snapshot des aktuellen Stands — Eingabe für jede Entscheidung."""
    ziel: int
    sendbar: int
    fehlend: int
    ziel_erreicht: bool
    erschoepft: bool        # Auffüllung lief durch, Ziel nicht erreicht
    gesucht_schon: bool     # mind. eine Suche/Auffüllung war erfolgreich
    letzter_fehler: str = ""  # nicht-leer, wenn das letzte Werkzeug fehlschlug


@dataclass
class Schritt:
    """Ein ausgeführter Agent-Schritt (Entscheidung + Werkzeug-Ergebnis)."""
    nummer: int
    entscheidung: Entscheidung
    ergebnis: object = None   # WerkzeugErgebnis

    @property
    def werkzeug(self) -> str:
        return self.entscheidung.werkzeug


@dataclass
class Laufergebnis:
    """Was ein Agent-Lauf zurückgibt — kundenfähig aufbereitbar."""
    auftrag: Auftrag
    schritte: list[Schritt]
    abschluss: Entscheidung
    lage: Lage

    @property
    def menschliches_tor(self) -> bool:
        return self.abschluss.typ == Aktionstyp.MENSCH_FRAGEN

    @property
    def erfolgreich(self) -> bool:
        return self.abschluss.typ in (Aktionstyp.FERTIG, Aktionstyp.MENSCH_FRAGEN)

    def kundentext(self) -> str:
        """Kundenfähiger Abschlusstext — ruhig, ehrlich, ohne Technik."""
        kopf = {
            Aktionstyp.MENSCH_FRAGEN: "🔔 Deine Entscheidung ist gefragt",
            Aktionstyp.AUFGEBEN: "ℹ️ Zwischenstand",
            Aktionstyp.FERTIG: "✅ Erledigt",
            Aktionstyp.WERKZEUG: "",
        }.get(self.abschluss.typ, "")
        return f"{kopf}\n\n{self.abschluss.begruendung}".strip()


# ─── Politik-Vertrag ─────────────────────────────────────────────────────────


class Politik(Protocol):
    def entscheide(
        self, auftrag: Auftrag, lage: Lage, verlauf: list[Schritt]
    ) -> Entscheidung: ...


# ─── Deterministische Politik ────────────────────────────────────────────────


class DeterministischePolitik:
    """Regelbasiertes Gehirn — läuft ohne API-Key und dient als Claude-Fallback.

    Bildet die Vertriebsleiter-Logik ab: erst suchen, bei Lücke selbstständig
    auffüllen, bei Erschöpfung ehrlich stoppen, bei Ziel-Erreichung ein hartes
    Tor (Mensch fragt nach Freigabe) öffnen. Der Agent sendet NIE selbst.
    """

    def entscheide(
        self, auftrag: Auftrag, lage: Lage, verlauf: list[Schritt]
    ) -> Entscheidung:
        # 1. Fehler im letzten Schritt → ehrlich stoppen, nicht blind weiter.
        if lage.letzter_fehler:
            return Entscheidung(
                Aktionstyp.AUFGEBEN,
                begruendung=(
                    "Bei der Suche ist etwas schiefgelaufen — ich stoppe lieber und "
                    "melde mich, statt blind weiterzumachen. Der bisherige Stand "
                    "bleibt erhalten."
                ),
            )

        # 2. Ziel erreicht → hartes Tor: Senden bestätigt der Mensch.
        if lage.ziel_erreicht:
            return Entscheidung(
                Aktionstyp.MENSCH_FRAGEN,
                begruendung=(
                    f"{lage.sendbar} saubere Leads sind bereit — das Ziel von "
                    f"{lage.ziel} ist erreicht. Soll ich die Mail-Vorschau öffnen? "
                    "Gesendet wird erst nach deiner Freigabe."
                ),
            )

        # 3. Noch nie gesucht → erste Suche starten.
        if not lage.gesucht_schon:
            return Entscheidung(
                Aktionstyp.WERKZEUG,
                "suche_starten",
                {},
                (
                    f"Ich starte die Suche für {auftrag.zielgruppe} in "
                    f"{auftrag.region} — Ziel: {lage.ziel} saubere Leads."
                ),
            )

        # 4. Lücke, aber Auffüllung schon ausgereizt → ehrlich aufgeben.
        if lage.erschoepft:
            return Entscheidung(
                Aktionstyp.AUFGEBEN,
                begruendung=(
                    f"{lage.sendbar} von {lage.ziel} sauberen Leads erreicht. "
                    "Die Zielgruppe ist in den durchsuchten Regionen ausgeschöpft — "
                    "mehr dieser Art gibt es dort kaum. Sag mir, ob wir mit diesen "
                    "starten oder die Kriterien anpassen."
                ),
            )

        # 5. Lücke → selbstständig auffüllen (angrenzende Regionen / Branchen).
        return Entscheidung(
            Aktionstyp.WERKZEUG,
            "auffuellung_starten",
            {},
            (
                f"Es fehlen noch {lage.fehlend} Leads. Ich suche selbstständig in "
                "angrenzenden Regionen und verwandten Branchen weiter."
            ),
        )


# ─── Claude-Politik (Reasoning-Kern) ─────────────────────────────────────────


class ClaudePolitik:
    """Claude als Reasoning-Gehirn. Fällt bei fehlendem Key/SDK oder bei einer
    unbrauchbaren Antwort sauber auf die deterministische Politik zurück.

    llm_fn: (system, user) -> str  — z. B. aus build_anthropic_llm(); oder None.
    """

    def __init__(self, llm_fn=None, fallback: Optional[Politik] = None):
        self._llm = llm_fn
        self._fallback: Politik = fallback or DeterministischePolitik()

    def entscheide(
        self, auftrag: Auftrag, lage: Lage, verlauf: list[Schritt]
    ) -> Entscheidung:
        if self._llm is None:
            return self._fallback.entscheide(auftrag, lage, verlauf)
        try:
            antwort = self._llm(self._system_prompt(), self._lage_prompt(auftrag, lage, verlauf))
            return self._parse(antwort)
        except Exception:
            # Jede Unsicherheit (kein JSON, unbekanntes Werkzeug, API-Fehler)
            # → verlässlicher deterministischer Pfad.
            return self._fallback.entscheide(auftrag, lage, verlauf)

    # --- Prompt-Bau ---

    @staticmethod
    def _system_prompt() -> str:
        zeilen = [
            "Du bist der Kampagnen-Stratege eines autonomen Vertriebs-Agenten.",
            "Dein Ziel: einen Lead-Auftrag bis zur Sende-Reife führen.",
            "Du wählst die NÄCHSTE einzelne Aktion aus den verfügbaren Werkzeugen.",
            "",
            "HARTE REGEL: Du sendest NIEMALS selbst. Sobald das Ziel erreicht ist und",
            "sendbare Leads bereit sind, wählst du 'mensch_fragen' — das Senden",
            "bestätigt immer der Mensch.",
            "",
            "Verfügbare Werkzeuge (nur diese Namen sind erlaubt):",
        ]
        for w in alle_werkzeuge():
            zeilen.append(f"  - {w.name}: {w.beschreibung}")
        zeilen += [
            "",
            "Antworte AUSSCHLIESSLICH mit einem JSON-Objekt, ohne weiteren Text:",
            '{"typ": "werkzeug"|"fertig"|"mensch_fragen"|"aufgeben",',
            ' "werkzeug": "<name oder leer>",',
            ' "parameter": {},',
            ' "begruendung": "<eine ruhige, kundenfähige Begründung, keine Technik>"}',
        ]
        return "\n".join(zeilen)

    @staticmethod
    def _lage_prompt(auftrag: Auftrag, lage: Lage, verlauf: list[Schritt]) -> str:
        zeilen = [
            f"Auftrag: {lage.ziel} Leads — {auftrag.zielgruppe} in {auftrag.region}.",
            f"Angebot: {auftrag.angebot}.",
            "",
            "Aktuelle Lage:",
            f"  - sendbare Leads: {lage.sendbar} von {lage.ziel} (es fehlen {lage.fehlend})",
            f"  - schon gesucht: {'ja' if lage.gesucht_schon else 'nein'}",
            f"  - Auffüllung ausgereizt: {'ja' if lage.erschoepft else 'nein'}",
        ]
        if lage.letzter_fehler:
            zeilen.append("  - Achtung: der letzte Schritt ist fehlgeschlagen.")
        if verlauf:
            zeilen.append("")
            zeilen.append("Bisherige Schritte:")
            for s in verlauf:
                z = s.ergebnis.zusammenfassung if s.ergebnis else ""
                zeilen.append(f"  {s.nummer}. {s.werkzeug}: {z}")
        zeilen += ["", "Was ist die nächste Aktion?"]
        return "\n".join(zeilen)

    # --- Antwort-Parsing ---

    @staticmethod
    def _parse(text: str) -> Entscheidung:
        """Extrahiert und validiert die JSON-Entscheidung. Bei Ungültigkeit:
        ValueError → entscheide() fängt → Fallback."""
        start = text.find("{")
        ende = text.rfind("}")
        if start < 0 or ende < 0 or ende <= start:
            raise ValueError("keine JSON-Struktur in der Antwort")
        obj = json.loads(text[start : ende + 1])

        typ = Aktionstyp(str(obj.get("typ", "")).strip())  # wirft bei ungültig
        werkzeug = (obj.get("werkzeug") or "").strip()
        parameter = obj.get("parameter") or {}
        if not isinstance(parameter, dict):
            parameter = {}
        begruendung = (obj.get("begruendung") or "").strip()

        if typ == Aktionstyp.WERKZEUG:
            # Nur erlaubte Werkzeuge. Sende-Werkzeuge sind nicht in werkzeug_namen()
            # → werden hier verworfen → Fallback (doppelte Absicherung).
            if werkzeug not in werkzeug_namen():
                raise ValueError(f"unbekanntes oder gesperrtes Werkzeug: {werkzeug!r}")

        return Entscheidung(typ=typ, werkzeug=werkzeug, parameter=parameter, begruendung=begruendung)


# ─── Speicher-Vertrag (Voll-Implementierung in Phase A.3) ───────────────────


class Speicher(Protocol):
    def aufzeichnen(self, auftrag: Auftrag, schritt: Schritt, lage: Lage) -> None: ...
    def abschluss(self, auftrag: Auftrag, ergebnis: Laufergebnis) -> None: ...


# ─── Der Agent-Loop ──────────────────────────────────────────────────────────


class Brain:
    """Der Agent-Loop: liest die Lage, lässt die Politik entscheiden, handelt,
    bewertet — bis eine terminale Entscheidung fällt oder das Schritt-Limit greift.
    """

    def __init__(
        self,
        kontext: AgentKontext,
        politik: Optional[Politik] = None,
        max_schritte: int = 12,
        speicher: Optional[Speicher] = None,
    ):
        self.kontext = kontext
        self.politik: Politik = politik or DeterministischePolitik()
        self.max_schritte = max_schritte
        self.speicher = speicher

    def fuehre_aus(self) -> Laufergebnis:
        verlauf: list[Schritt] = []
        abschluss: Optional[Entscheidung] = None
        lage = self._lage_lesen(verlauf)

        for nummer in range(1, self.max_schritte + 1):
            lage = self._lage_lesen(verlauf)
            entscheidung = self._guardrail(
                self.politik.entscheide(self.kontext.auftrag, lage, verlauf)
            )

            if entscheidung.ist_terminal():
                abschluss = entscheidung
                break

            werkzeug = werkzeug_nach_name(entscheidung.werkzeug)
            # _guardrail garantiert: werkzeug existiert hier. Defensive Prüfung:
            if werkzeug is None:  # pragma: no cover
                abschluss = self._aufgeben_unbekannt(entscheidung.werkzeug)
                break

            ergebnis = werkzeug.ausfuehren(self.kontext, entscheidung.parameter)
            schritt = Schritt(nummer=nummer, entscheidung=entscheidung, ergebnis=ergebnis)
            verlauf.append(schritt)
            if self.speicher is not None:
                self.speicher.aufzeichnen(self.kontext.auftrag, schritt, lage)
        else:
            # Schleife ohne terminale Entscheidung ausgelaufen → Schritt-Limit.
            abschluss = Entscheidung(
                Aktionstyp.AUFGEBEN,
                begruendung=(
                    "Ich habe die Obergrenze an Schritten erreicht und stoppe, um "
                    "nicht im Kreis zu laufen. Der erreichte Stand ist gesichert — "
                    "sag mir, wie es weitergehen soll."
                ),
            )

        lage = self._lage_lesen(verlauf)
        laufergebnis = Laufergebnis(
            auftrag=self.kontext.auftrag,
            schritte=verlauf,
            abschluss=abschluss,
            lage=lage,
        )
        if self.speicher is not None:
            self.speicher.abschluss(self.kontext.auftrag, laufergebnis)
        return laufergebnis

    # --- Loop-Interna ---

    def _guardrail(self, entscheidung: Entscheidung) -> Entscheidung:
        """Erzwingt die Sicherheitsgrenzen technisch — vor jeder Ausführung."""
        if entscheidung.typ != Aktionstyp.WERKZEUG:
            return entscheidung

        # Hartes Tor: niemals selbst senden.
        if entscheidung.werkzeug in SENDE_WERKZEUGE_GESPERRT:
            return Entscheidung(
                Aktionstyp.MENSCH_FRAGEN,
                begruendung=(
                    "Hier ist eine menschliche Freigabe nötig — das Senden "
                    "bestätigst nur du. Sag mir Bescheid, wenn ich loslegen soll."
                ),
            )

        # Unbekanntes Werkzeug → ehrlich stoppen statt raten.
        if werkzeug_nach_name(entscheidung.werkzeug) is None:
            return self._aufgeben_unbekannt(entscheidung.werkzeug)

        return entscheidung

    @staticmethod
    def _aufgeben_unbekannt(name: str) -> Entscheidung:
        return Entscheidung(
            Aktionstyp.AUFGEBEN,
            begruendung=(
                "Mir fehlt dafür das passende Werkzeug — ich stoppe lieber und "
                "melde mich, statt etwas Falsches zu tun."
            ),
        )

    def _lage_lesen(self, verlauf: list[Schritt]) -> Lage:
        """observe: liest den aktuellen Stand und leitet die Lage ab."""
        bericht = werkzeug_nach_name("bericht_lesen").ausfuehren(self.kontext, {})
        daten = bericht.daten if bericht.erfolg else {}

        sendbar = int(daten.get("pipeline_sendbar", daten.get("sendable", 0)) or 0)
        ziel = int(self.kontext.auftrag.lead_anzahl)
        fehlend = max(0, ziel - sendbar)
        ziel_erreicht = ziel > 0 and sendbar >= ziel

        gesucht_schon = any(
            s.werkzeug in ("suche_starten", "auffuellung_starten")
            and s.ergebnis is not None
            and s.ergebnis.erfolg
            for s in verlauf
        )

        # Erschöpft = eine vollständige Auffüllung lief, erreichte das Ziel aber
        # nicht. Eine weitere Auffüllung würde dieselben Varianten abklappern —
        # also nicht endlos wiederholen, sondern ehrlich stoppen.
        erschoepft = any(
            s.werkzeug == "auffuellung_starten"
            and s.ergebnis is not None
            and s.ergebnis.erfolg
            and not s.ergebnis.daten.get("ziel_erreicht", False)
            for s in verlauf
        )

        letzter_fehler = ""
        if verlauf:
            letzte = verlauf[-1]
            if letzte.ergebnis is not None and not letzte.ergebnis.erfolg:
                letzter_fehler = letzte.ergebnis.fehler or letzte.ergebnis.zusammenfassung

        return Lage(
            ziel=ziel,
            sendbar=sendbar,
            fehlend=fehlend,
            ziel_erreicht=ziel_erreicht,
            erschoepft=erschoepft,
            gesucht_schon=gesucht_schon,
            letzter_fehler=letzter_fehler,
        )


# ─── Komfort-Factory (dünne Anbindung, Phase A.5) ───────────────────────────


def baue_brain(
    kontext: AgentKontext,
    api_key: Optional[str] = None,
    max_schritte: int = 12,
    speicher: Optional[Speicher] = None,
) -> Brain:
    """Baut einen Brain mit Claude als Reasoning-Kern.

    Ohne Key/SDK liefert build_anthropic_llm() None → ClaudePolitik nutzt intern
    die deterministische Politik. Der Agent läuft also immer — mit oder ohne Key.
    """
    from product.operator.llm_anthropic import build_anthropic_llm

    llm_fn = build_anthropic_llm(api_key)
    politik = ClaudePolitik(llm_fn)
    return Brain(kontext, politik=politik, max_schritte=max_schritte, speicher=speicher)
