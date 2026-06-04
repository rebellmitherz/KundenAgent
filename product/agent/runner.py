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
