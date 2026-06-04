"""Bestätigungs-Gate — der einzige Weg von ENTWURF zu BESTAETIGT.

Präsentiert den Auftrags-Entwurf, erkennt Ja/Nein/Korrektur in natürlicher
Sprache, und ruft auftrag.bestaetigen() erst nach eindeutigem Ja auf.

Zustandslos: Der Aufrufer (Telegram-Front / UI) verwaltet den Dialog-State.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from product.operator.order_schema import Auftrag, AuftragsStatus


class ConfirmStatus(str, Enum):
    BESTAETIGT = "bestaetigt"    # Kunde hat Ja gesagt → auftrag.bestaetigen() wurde gerufen
    ABGELEHNT  = "abgelehnt"     # Kunde hat Nein gesagt → Auftrag verwerfen
    KORREKTUR  = "korrektur"     # Kunde will etwas ändern → Feld + neuer Wert
    UNKLAR     = "unklar"        # Nicht eindeutig → Rückfrage nötig


@dataclass
class ConfirmErgebnis:
    status: ConfirmStatus
    meldung: str = ""
    korrektur_feld: Optional[str] = None   # z. B. "region"
    korrektur_wert: Optional[str] = None   # z. B. "Bayern"
    rueckfrage: str = ""


# --- Ja-Muster ---------------------------------------------------------------
_JA = re.compile(
    r"\b(ja|jo|yes|yep|genau|stimmt|passt|ok|okay|richtig|korrekt|"
    r"starten|los|starte|mach|machen|weiter|bestätige|bestätigt|"
    r"super|perfekt|alles klar|top|gut so)\b",
    re.IGNORECASE,
)

# --- Nein-Muster -------------------------------------------------------------
_NEIN = re.compile(
    r"\b(nein|nee|ne|no|stopp|stop|abbrechen|abbruch|verwerfen|"
    r"vergiss|vergessen|nicht|falsch|cancel|weg damit)\b",
    re.IGNORECASE,
)

# --- Korrektur-Muster: "Region: Bayern" / "ändere Region zu Bayern" ----------
_KORREKTUR_DIREKT = re.compile(
    r"\b(zielgruppe|region|anzahl|lead.anzahl|angebot)\s*[:\-=]\s*(.+)",
    re.IGNORECASE,
)
_KORREKTUR_VERB = re.compile(
    r"\b(?:ändere?|änder|korrigiere?|korrigier|setze?|setz)\s+"
    r"(zielgruppe|region|anzahl|angebot)\s+(?:auf|zu|in|=)?\s*(.+)",
    re.IGNORECASE,
)
# Alias-Map für Feldnamen
_FELD_ALIAS = {
    "zielgruppe": "zielgruppe", "region": "region",
    "anzahl": "lead_anzahl", "lead-anzahl": "lead_anzahl", "lead_anzahl": "lead_anzahl",
    "angebot": "angebot",
}


class ConfirmGate:

    def frage_stellen(self, auftrag: Auftrag) -> str:
        """Erzeugt die Bestätigungs-Nachricht, die dem Kunden gezeigt wird."""
        if auftrag.status != AuftragsStatus.ENTWURF:
            raise ValueError(
                f"Nur ENTWURF kann bestätigt werden, ist: {auftrag.status.value}"
            )
        return (
            f"Ich habe deinen Auftrag so verstanden:\n\n"
            f"{auftrag.als_bestaetigung()}\n\n"
            f"Passt das so?\n"
            f"'Ja, starten' oder sag mir, was ich ändern soll."
        )

    def verarbeite_antwort(self, text: str, auftrag: Auftrag) -> ConfirmErgebnis:
        """Verarbeitet die Kundenantwort auf die Bestätigungs-Frage.

        Reihenfolge: Korrektur prüfen → Ja → Nein → unklar.
        Korrektur hat Vorrang, damit "nein, region: Bayern" korrekt erkannt wird.
        """
        stripped = text.strip()

        # 1. Korrektur-Check (Vorrang vor Ja/Nein)
        korrektur = self._erkenne_korrektur(stripped)
        if korrektur:
            feld, wert = korrektur
            return ConfirmErgebnis(
                status=ConfirmStatus.KORREKTUR,
                meldung=f"Ich passe {feld} an.",
                korrektur_feld=feld,
                korrektur_wert=wert.strip(),
            )

        # 2. Ja-Check
        if _JA.search(stripped) and not _NEIN.search(stripped):
            auftrag.bestaetigen()
            return ConfirmErgebnis(
                status=ConfirmStatus.BESTAETIGT,
                meldung="Auftrag bestätigt. Ich starte die Suche.",
            )

        # 3. Nein-Check
        if _NEIN.search(stripped):
            return ConfirmErgebnis(
                status=ConfirmStatus.ABGELEHNT,
                meldung="Auftrag verworfen. Sag mir einfach, was du stattdessen suchst.",
            )

        # 4. Unklare Antwort
        return ConfirmErgebnis(
            status=ConfirmStatus.UNKLAR,
            rueckfrage=(
                "Ich bin nicht sicher, ob das ein Ja oder eine Änderung ist.\n"
                "Antworte 'Ja, starten' oder nenn mir, was ich anpassen soll\n"
                "(z. B. 'Region: Bayern' oder 'Anzahl: 50')."
            ),
        )

    @staticmethod
    def _erkenne_korrektur(text: str) -> Optional[tuple[str, str]]:
        for pattern in (_KORREKTUR_VERB, _KORREKTUR_DIREKT):
            m = pattern.search(text)
            if m:
                feld_roh = m.group(1).lower().replace("-", "_").replace(" ", "_")
                feld = _FELD_ALIAS.get(feld_roh)
                if feld:
                    return feld, m.group(2)
        return None
