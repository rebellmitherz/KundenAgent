"""Auftrags-Schema — das Fundament der Produktschicht.

Jeder Kundenauftrag wird in dieses Schema gegossen, bevor die Bridge
irgendetwas tut. Nur bestätigte Aufträge (status=BESTAETIGT) darf die
Bridge ausführen.

Packaging-Regel: keine hardcodierten Pfade hier.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


class ErlaubteAktion(str, Enum):
    SUCHEN_AUFBEREITEN = "suchen_aufbereiten"
    # V2: VORSCHAU_ERSTELLEN = "vorschau_erstellen"
    # V2: SENDEN_NACH_FREIGABE = "senden_nach_freigabe"


class AuftragsStatus(str, Enum):
    ENTWURF = "entwurf"
    BESTAETIGT = "bestaetigt"
    LAEUFT = "laeuft"
    FERTIG = "fertig"
    FEHLER = "fehler"
    # V2: WARTET_AUF_FREIGABE = "wartet_auf_freigabe"


@dataclass
class Qualitaetskriterien:
    telefon_pflicht: bool = True
    persoenlicher_ansprechpartner: bool = True
    keine_konzerne: bool = True
    keine_generischen_mails: bool = True
    keine_dubletten: bool = True

    def als_text(self) -> str:
        aktiv = []
        if self.telefon_pflicht:
            aktiv.append("Telefon Pflicht")
        if self.persoenlicher_ansprechpartner:
            aktiv.append("persönl. Ansprechpartner bevorzugt")
        if self.keine_konzerne:
            aktiv.append("keine Konzerne")
        if self.keine_generischen_mails:
            aktiv.append("keine generischen Mails")
        if self.keine_dubletten:
            aktiv.append("keine Dubletten")
        return ", ".join(aktiv) if aktiv else "Standard"


@dataclass
class Ergebnis:
    leads_gefunden: int = 0
    leads_sauber: int = 0
    leads_fehlend: int = 0
    zielgruppe_erschoepft: bool = False
    vorschlaege: list = field(default_factory=list)
    bericht: str = ""


def _auftrags_id(zielgruppe: str, region: str) -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "_", f"{zielgruppe}_{region}".lower())[:30]
    return f"{ts}_{slug}"


@dataclass
class Auftrag:
    zielgruppe: str
    region: str
    lead_anzahl: int
    angebot: str
    qualitaet: Qualitaetskriterien = field(default_factory=Qualitaetskriterien)
    erlaubte_aktion: ErlaubteAktion = ErlaubteAktion.SUCHEN_AUFBEREITEN
    status: AuftragsStatus = field(default=AuftragsStatus.ENTWURF)
    auftrags_id: str = field(default="")
    erstellt_am: str = field(default="")
    ergebnis: Optional[Ergebnis] = field(default=None)

    def __post_init__(self) -> None:
        if not self.auftrags_id:
            self.auftrags_id = _auftrags_id(self.zielgruppe, self.region)
        if not self.erstellt_am:
            self.erstellt_am = datetime.now(tz=timezone.utc).isoformat()

    # --- Lebenszyklus ---

    def bestaetigen(self) -> None:
        if self.status != AuftragsStatus.ENTWURF:
            raise ValueError(f"Kann nur Entwurf bestätigen, nicht: {self.status}")
        self.status = AuftragsStatus.BESTAETIGT

    def starten(self) -> None:
        if self.status != AuftragsStatus.BESTAETIGT:
            raise ValueError(f"Nur bestätigte Aufträge können starten, nicht: {self.status}")
        self.status = AuftragsStatus.LAEUFT

    def abschliessen(self, ergebnis: Ergebnis) -> None:
        self.ergebnis = ergebnis
        self.status = AuftragsStatus.FERTIG

    def fehler_setzen(self, bericht: str) -> None:
        self.ergebnis = Ergebnis(bericht=bericht)
        self.status = AuftragsStatus.FEHLER

    # --- Darstellung für den Kunden ---

    def als_bestaetigung(self) -> str:
        return (
            f"🎯 Zielgruppe:        {self.zielgruppe}\n"
            f"📍 Region:            {self.region}\n"
            f"🔢 Lead-Anzahl:       {self.lead_anzahl}\n"
            f"💼 Angebot:           {self.angebot}\n"
            f"✅ Qualität:          {self.qualitaet.als_text()}\n"
            f"🤖 Erlaubte Aktion:   {self.erlaubte_aktion.value}"
        )

    # --- Persistenz (datei-basiert) ---

    def to_dict(self) -> dict:
        d = asdict(self)
        d["erlaubte_aktion"] = self.erlaubte_aktion.value
        d["status"] = self.status.value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def speichern(self, orders_dir: Path) -> Path:
        orders_dir.mkdir(parents=True, exist_ok=True)
        pfad = orders_dir / f"{self.auftrags_id}.json"
        pfad.write_text(self.to_json(), encoding="utf-8")
        return pfad

    @classmethod
    def from_dict(cls, d: dict) -> "Auftrag":
        q_data = d.pop("qualitaet", {})
        qualitaet = Qualitaetskriterien(**q_data) if q_data else Qualitaetskriterien()
        e_data = d.pop("ergebnis", None)
        ergebnis = Ergebnis(**e_data) if e_data else None
        d["erlaubte_aktion"] = ErlaubteAktion(d["erlaubte_aktion"])
        d["status"] = AuftragsStatus(d["status"])
        return cls(qualitaet=qualitaet, ergebnis=ergebnis, **d)

    @classmethod
    def laden(cls, pfad: Path) -> "Auftrag":
        return cls.from_dict(json.loads(pfad.read_text(encoding="utf-8")))
