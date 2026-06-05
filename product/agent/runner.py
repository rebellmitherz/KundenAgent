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

import threading
from pathlib import Path
from typing import Callable, Optional

from product.agent.brain import Brain, Laufergebnis, baue_brain
from product.agent.campaign import KampagnenSpeicher
from product.agent.erledigt import ErledigtSpeicher
from product.agent.funnel import funnel_aus_rohdaten, funnel_bericht
from product.agent.memory import LaufSpeicher
from product.agent.replies import antworten_bericht, termine
from product.agent.replies import pruef_termine as _pruef_termine
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
        self._kampagnen = KampagnenSpeicher(data_dir)
        self._erledigt = ErledigtSpeicher(data_dir)

    # ----------------------------------------------------------------- Steuern

    def starten(self, auftrag: Auftrag) -> Laufergebnis:
        """Setzt den Agenten auf einen Auftrag (synchron) und persistiert den Lauf.

        Der Auftrag muss bestätigt sein (BESTAETIGT) — sonst kann die Engine-Bridge
        die Suche nicht ausführen. Wir bestätigen einen Entwurf hier NICHT
        automatisch: die Bestätigung ist eine bewusste Kunden-/Admin-Handlung.
        """
        brain = self._baue_brain(auftrag)
        return brain.fuehre_aus()

    def starten_im_hintergrund(
        self, auftrag: Auftrag, fertig_callback: Optional[Callable[[Laufergebnis], None]] = None
    ) -> str:
        """Startet einen Auftrag asynchron (für die Mini-UI).

        Persistiert sofort einen 'laeuft'-Datensatz (damit die UI den Lauf direkt
        sieht) und führt den Agenten in einem Daemon-Thread aus. Gibt die
        auftrags_id zurück. Der Agent sendet NIE selbst — er stoppt am harten Tor.
        """
        if auftrag.status == AuftragsStatus.ENTWURF:
            auftrag.bestaetigen()
        self._speicher.lauf_anlegen(auftrag)

        def _arbeit() -> None:
            try:
                ergebnis = self._baue_brain(auftrag).fuehre_aus()
                if fertig_callback:
                    fertig_callback(ergebnis)
            except Exception:
                # Absturzsicher: der 'laeuft'-Datensatz bleibt, Fehler verschluckt.
                pass

        threading.Thread(target=_arbeit, daemon=True).start()
        return auftrag.auftrags_id

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
        Jede Antwort wird mit 'erledigt' markiert (abgeschlossener Termin).
        """
        if self._bridge is None:
            return []
        try:
            roh = self._bridge.antworten_lesen(limit=limit)
        except Exception:
            return []
        erledigte = self._erledigt.erledigte_keys()
        for a in roh:
            a["erledigt"] = a.get("entry_key", "") in erledigte
        return roh

    def antworten_abrufen(self, limit: int = 30) -> dict:
        """E: Holt aktiv neue Antworten aus dem Postfach (read-only, kein Versand).

        Delegiert an die Bridge, die alle Auto-Send-Gates scoped aushält. Danach
        stehen neue Antworten via antworten()/termin_signale() bereit. Gibt einen
        kundenfähigen Statusdict zurück.
        """
        if self._bridge is None:
            return {"ok": False, "meldung": "Engine nicht verbunden."}
        if not hasattr(self._bridge, "antworten_abrufen"):
            return {"ok": False, "meldung": "Abruf nicht verfügbar."}
        try:
            erg = self._bridge.antworten_abrufen(limit=limit)
            return {
                "ok": erg.ok,
                "neu": erg.leads_gefunden,
                "gesamt": erg.leads_sauber,
                "meldung": erg.meldung,
            }
        except Exception as exc:
            return {"ok": False, "meldung": f"Abruf-Fehler: {exc}"}

    def antworten_bericht(self, limit: int = 30) -> str:
        """Kundenfähige Zusammenfassung der Antworten (hebt Terminwünsche hervor)."""
        return antworten_bericht(self.antworten(limit=limit))

    def termin_signale(self, limit: int = 30) -> list[dict]:
        """Nur OFFENE, **bestätigte** Termin-Signale — erledigte und durch die
        Signalqualitäts-Triage herabgestufte Signale werden ausgeblendet (F1)."""
        return [a for a in termine(self.antworten(limit=limit)) if not a.get("erledigt")]

    def pruef_termine(self, limit: int = 30) -> list[dict]:
        """Offene Signale, die wie ein Termin markiert waren, dem Text nach aber
        widersprüchlich sind (F1) — dem Menschen zur Prüfung, nie als sicherer
        Termin."""
        return [a for a in _pruef_termine(self.antworten(limit=limit)) if not a.get("erledigt")]

    def termin_abschliessen(self, firma_oder_key: str) -> dict:
        """Markiert einen Termin als erledigt (read-only zur Engine, agent-lokal).

        Sucht in den offenen Terminen nach Firmenname (Teilstring, case-insensitiv)
        oder exaktem entry_key. Bei Mehrdeutigkeit wird nachgefragt.
        """
        suche = (firma_oder_key or "").strip().lower()
        if not suche:
            return {"ok": False, "meldung": "Bitte sag mir, welcher Termin erledigt ist."}

        offene = self.termin_signale()
        if not offene:
            return {"ok": False, "meldung": "Aktuell sind keine offenen Termine vorhanden."}

        treffer = [
            a for a in offene
            if a.get("entry_key", "").lower() == suche
            or suche in (a.get("firma", "").lower())
        ]
        if not treffer:
            namen = ", ".join(a.get("firma", "?") for a in offene)
            return {"ok": False, "meldung": f"Keinen offenen Termin zu '{firma_oder_key}' gefunden. Offen: {namen}"}
        if len(treffer) > 1:
            namen = ", ".join(a.get("firma", "?") for a in treffer)
            return {"ok": False, "meldung": f"Mehrere Treffer ({namen}). Bitte genauer angeben."}

        a = treffer[0]
        neu = self._erledigt.abschliessen(a.get("entry_key", ""), a.get("firma", ""))
        if not neu:
            return {"ok": True, "meldung": f"{a.get('firma','?')} war bereits abgeschlossen."}
        return {"ok": True, "firma": a.get("firma", ""), "meldung": f"✅ Termin mit {a.get('firma','?')} als erledigt markiert."}

    # ----------------------------------------------------------------- Kampagnen-Trichter (Phase C)

    def funnel(self, campaign: Optional[str] = None) -> dict:
        """Live-Trichter: je Lead die Stufe (gefunden→bereit→angeschrieben→
        geantwortet→termin) plus Zählung. Read-only, kein Versand."""
        if self._bridge is None:
            return {"gesamt": 0, "stufen": {}, "leads": []}
        try:
            roh = self._bridge.kampagne_rohdaten(campaign=campaign)
        except Exception:
            return {"gesamt": 0, "stufen": {}, "leads": []}
        return funnel_aus_rohdaten(roh)

    def funnel_bericht(self, campaign: Optional[str] = None) -> str:
        """Kundenfähige Trichter-Übersicht inkl. Trend zum letzten Snapshot."""
        f = self.funnel(campaign)
        letzter = self._kampagnen.letzter(campaign or "gesamt")
        vorher = letzter.get("stufen") if letzter else None
        return funnel_bericht(f, vorher=vorher)

    def funnel_snapshot(self, campaign: Optional[str] = None) -> dict:
        """Berechnet den Trichter und schreibt ihn in den Kampagnen-Verlauf
        (persistent über Neustarts). Gibt den Live-Trichter zurück."""
        f = self.funnel(campaign)
        self._kampagnen.snapshot_speichern(campaign or "gesamt", f)
        return f

    def funnel_verlauf(self, campaign: Optional[str] = None) -> list[dict]:
        """Bisherige Snapshots (Trend) einer Kampagne."""
        return self._kampagnen.verlauf(campaign or "gesamt")

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
