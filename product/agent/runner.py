"""Agent-Runner — die EINE geteilte Anbindung für Telegram + Mini-UI (Phase A.5).

Verdrahtet Kontext + Brain + Lauf-Speicher zu einem schlanken Einstieg:
  starten(auftrag) → Agent läuft (suchen + selbst auffüllen) → Laufergebnis,
  hält an harten Toren (Senden = Mensch). Der Lauf wird persistiert.

Beide Front-Ends rufen denselben Runner — keine doppelte Logik. Threading
(Hintergrund-Lauf) ist Sache des Front-Ends; der Runner bleibt synchron + simpel.

Sicherheit: Der Agent sendet NIE selbst (brain.py erzwingt das). Der Runner
fügt keine Sende-Pfade hinzu.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from product.agent.brain import Brain, Laufergebnis, baue_brain
from product.agent.memory import LaufSpeicher
from product.agent.replies import antworten_bericht, termine
from product.agent.tools import AgentKontext
from product.operator.order_schema import Auftrag, AuftragsStatus


class AgentRunner:
    """Setzt den Agenten auf einen Auftrag und macht die Läufe lesbar.

    bridge:    EngineBridge (oder kompatibler Mock) — die einzige Engine-Leitung.
    data_dir:  Wurzel für den Lauf-Speicher (<data_dir>/agent/).
    reporter:  optionaler Reporter für reichere Lage-Berichte.
    api_key:   optional — Claude als Reasoning-Kern; ohne Key deterministisch.
    """

    def __init__(
        self,
        bridge,
        data_dir: str | Path,
        reporter=None,
        api_key: Optional[str] = None,
        max_schritte: int = 12,
    ):
        self._bridge = bridge
        self._reporter = reporter
        self._api_key = api_key
        self._max_schritte = max_schritte
        self._speicher = LaufSpeicher(data_dir)

    # ----------------------------------------------------------------- Steuern

    def starten(self, auftrag: Auftrag) -> Laufergebnis:
        """Setzt den Agenten auf einen Auftrag (synchron) und persistiert den Lauf.

        Der Auftrag muss bestätigt sein (BESTAETIGT) — sonst kann die Engine-Bridge
        die Suche nicht ausführen. Wir bestätigen einen Entwurf hier NICHT
        automatisch: die Bestätigung ist eine bewusste Kunden-/Admin-Handlung.
        """
        brain = self._baue_brain(auftrag)
        return brain.fuehre_aus()

    def _baue_brain(self, auftrag: Auftrag) -> Brain:
        kontext = AgentKontext(
            auftrag=auftrag, bridge=self._bridge, reporter=self._reporter
        )
        return baue_brain(
            kontext,
            api_key=self._api_key,
            max_schritte=self._max_schritte,
            speicher=self._speicher,
        )

    # ----------------------------------------------------------------- Hartes Tor: Senden

    def freigeben(
        self, auftrags_id: str, limit: int = 20, *, bestaetigt: bool = False
    ) -> dict:
        """Versendet die Mails eines Laufs — NUR nach menschlicher Bestätigung.

        Dreifache Absicherung (fail-closed):
          1. bestaetigt muss True sein (menschlicher Freigabe-Klick).
          2. Der Lauf muss existieren UND am harten Tor stehen
             (Status 'wartet_auf_mensch') — kein Senden für unfertige Läufe,
             kein versehentliches Doppel-Senden.
          3. Die Bridge erzwingt die Sende-Bestätigung zusätzlich technisch.
        Der Agent-Loop ruft diese Methode NIE — sie ist kein Werkzeug.
        """
        if not bestaetigt:
            return {"ok": False, "meldung": "Freigabe ohne Bestätigung abgelehnt."}

        rec = self._speicher.lesen(auftrags_id)
        if rec is None:
            return {"ok": False, "meldung": "Unbekannter Lauf — nichts zu senden."}
        if rec.get("status") != "wartet_auf_mensch":
            return {
                "ok": False,
                "meldung": (
                    f"Lauf ist nicht freigabebereit (Status: {rec.get('status')}). "
                    "Freigabe nur möglich, wenn der Agent am Tor wartet."
                ),
            }
        if self._bridge is None:
            return {"ok": False, "meldung": "Engine nicht verbunden."}

        ergebnis = self._bridge.freigabe_ausfuehren(limit=limit, bestaetigt=True)
        self._speicher.freigabe_aufzeichnen(
            auftrags_id,
            gesendet=ergebnis.leads_sauber,
            meldung=ergebnis.meldung,
            ok=ergebnis.ok,
        )
        return {
            "ok": ergebnis.ok,
            "gesendet": ergebnis.leads_sauber,
            "meldung": ergebnis.meldung,
        }

    # ----------------------------------------------------------------- Antworten (read-only)

    def antworten(self, limit: int = 30) -> list[dict]:
        """Liest eingehende Antworten (read-only) — kundenfähige Felder.

        Kein Versand, nichts das senden könnte. Gibt [] wenn keine Bridge.
        """
        if self._bridge is None:
            return []
        try:
            return self._bridge.antworten_lesen(limit=limit)
        except Exception:
            return []

    def antworten_bericht(self, limit: int = 30) -> str:
        """Kundenfähige Zusammenfassung der Antworten (hebt Terminwünsche hervor)."""
        return antworten_bericht(self.antworten(limit=limit))

    def termin_signale(self, limit: int = 30) -> list[dict]:
        """Nur Antworten mit Terminwunsch — das harte Signal (für Phase D)."""
        return termine(self.antworten(limit=limit))

    # ----------------------------------------------------------------- Nachfassen

    def nachfass_faellig(self, limit: int = 50) -> list[dict]:
        """Read-only: Wer ist fürs Nachfassen fällig? Kein Versand."""
        if self._bridge is None:
            return []
        try:
            return self._bridge.followups_faellig(limit=limit)
        except Exception:
            return []

    def nachfassen(
        self, auftrags_id: str, limit: int = 20, *, bestaetigt: bool = False
    ) -> dict:
        """Nachfass-Versand — NUR nach menschlicher Bestätigung.

        Wie freigeben() dreifach gesichert: bestaetigt=True nötig + der Lauf muss
        bereits gesendet haben (Status 'gesendet' oder 'nachgefasst') + die Bridge
        erzwingt die Sende-Bestätigung zusätzlich. Kein Werkzeug des Agent-Loops.
        """
        if not bestaetigt:
            return {"ok": False, "meldung": "Nachfassen ohne Bestätigung abgelehnt."}
        rec = self._speicher.lesen(auftrags_id)
        if rec is None:
            return {"ok": False, "meldung": "Unbekannter Lauf — nichts nachzufassen."}
        if rec.get("status") not in ("gesendet", "nachgefasst"):
            return {
                "ok": False,
                "meldung": (
                    f"Lauf ist nicht nachfass-bereit (Status: {rec.get('status')}). "
                    "Nachfassen ist erst nach dem ersten Versand möglich."
                ),
            }
        if self._bridge is None:
            return {"ok": False, "meldung": "Engine nicht verbunden."}

        ergebnis = self._bridge.followup_ausfuehren(limit=limit, bestaetigt=True)
        self._speicher.nachfass_aufzeichnen(
            auftrags_id,
            nachgefasst=ergebnis.leads_sauber,
            meldung=ergebnis.meldung,
            ok=ergebnis.ok,
        )
        return {
            "ok": ergebnis.ok,
            "nachgefasst": ergebnis.leads_sauber,
            "meldung": ergebnis.meldung,
        }

    # ----------------------------------------------------------------- Lesen

    def laeufe(self) -> list[dict]:
        """Kompakte Übersicht aller Agent-Läufe (für Dashboard/Status)."""
        return self._speicher.alle_laeufe()

    def lauf(self, auftrags_id: str) -> Optional[dict]:
        """Vollständiger Datensatz eines Laufs. None wenn unbekannt."""
        return self._speicher.lesen(auftrags_id)

    @property
    def speicher(self) -> LaufSpeicher:
        return self._speicher
