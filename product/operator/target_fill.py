"""Target Fill Mode — mehrrundige Auffüllung bis zum Zielwert.

Das Kernversprechen: Wenn der Kunde 1000 saubere Leads will und Runde 1 nur 50
liefert, erkennt der Manager die Lücke, plant neue Suchvarianten (angrenzende
Regionen, verwandte Branchen), führt sie aus, und stoppt sauber wenn:
  - das Ziel erreicht ist, ODER
  - die Zielgruppe ausgeschöpft ist (mehrere Runden ohne nennenswerten Zuwachs),
  - ODER alle Varianten durch sind.

Dubletten: Die Engine dedupliziert selbst per stabilem entry_key
(E-Mail/Domain/Firma-Hash). Der kumulative "sendbare" Stand aus der Pipeline ist
daher automatisch dublettenfrei — der Zuwachs pro Runde sind echte neue Leads.

Qualität vor Menge: gemessen wird NUR der sendbare Stand (Telefon Pflicht +
ready_to_send=yes), nie die Roh-Trefferzahl.

Dieses Modul ruft die Engine ausschließlich über die Bridge auf (suchen +
status_lesen). Kein Send-Pfad, kein Engine-Kern-Zugriff.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, Protocol

from product.operator.expansion_maps import region_erweiterungen, verwandte_branchen
from product.operator.order_schema import Auftrag, ErlaubteAktion, Qualitaetskriterien


class VariantenTyp(str, Enum):
    ORIGINAL = "original"
    REGION   = "region"
    BRANCHE  = "branche"


class AbbruchGrund(str, Enum):
    ZIEL_ERREICHT     = "ziel_erreicht"
    ERSCHOEPFT        = "zielgruppe_erschoepft"
    VARIANTEN_DURCH   = "alle_varianten_durch"
    MAX_RUNDEN        = "max_runden_erreicht"
    FEHLER            = "fehler"


@dataclass
class Variante:
    typ: VariantenTyp
    zielgruppe: str
    region: str

    def beschreibung(self) -> str:
        if self.typ == VariantenTyp.ORIGINAL:
            return f"{self.zielgruppe} in {self.region}"
        if self.typ == VariantenTyp.REGION:
            return f"{self.zielgruppe} in {self.region} (Region erweitert)"
        return f"{self.zielgruppe} in {self.region} (verwandte Branche)"


@dataclass
class RundenErgebnis:
    runde: int
    variante: Variante
    sendbar_vorher: int
    sendbar_nachher: int
    fehler: str = ""

    @property
    def zuwachs(self) -> int:
        return max(0, self.sendbar_nachher - self.sendbar_vorher)


@dataclass
class TargetFillBericht:
    ziel: int
    start_sendbar: int
    end_sendbar: int
    abbruch_grund: AbbruchGrund
    runden: list[RundenErgebnis] = field(default_factory=list)

    @property
    def gewonnen(self) -> int:
        return max(0, self.end_sendbar - self.start_sendbar)

    @property
    def fehlend(self) -> int:
        return max(0, self.ziel - self.end_sendbar)

    @property
    def ziel_erreicht(self) -> bool:
        return self.end_sendbar >= self.ziel


# Bridge-Vertrag: nur die zwei Methoden, die Target Fill braucht.
class _BridgeProtokoll(Protocol):
    def suchen(self, auftrag: Auftrag): ...
    def status_lesen(self) -> dict: ...


# Fortschritt-Callback: (runde, gesamt_runden, RundenErgebnis) -> None
FortschrittFn = Callable[[int, int, RundenErgebnis], None]


class TargetFillManager:
    def __init__(
        self,
        bridge: _BridgeProtokoll,
        max_runden: int = 8,
        erschoepft_schwelle: int = 3,    # Zuwachs darunter = "leere" Runde
        erschoepft_runden: int = 2,      # so viele leere Runden in Folge → Stop
    ):
        self._bridge = bridge
        self._max_runden = max_runden
        self._erschoepft_schwelle = erschoepft_schwelle
        self._erschoepft_runden = erschoepft_runden

    # ----------------------------------------------------------------- Planung

    def plane_varianten(self, basis: Auftrag) -> list[Variante]:
        """Erzeugt die geordnete Variantenliste: original → Regionen → Branchen.

        Reihenfolge bewusst: erst die Originalsuche maximal ausschöpfen, dann
        in angrenzende Regionen, dann in verwandte Branchen (am weitesten weg
        von der ursprünglichen Zielgruppe).
        """
        varianten: list[Variante] = [
            Variante(VariantenTyp.ORIGINAL, basis.zielgruppe, basis.region)
        ]

        # Regionale Erweiterungen (gleiche Zielgruppe, neue Gebiete)
        for gebiet in region_erweiterungen(basis.region):
            varianten.append(Variante(VariantenTyp.REGION, basis.zielgruppe, gebiet))

        # Verwandte Branchen (in der Originalregion)
        for branche in verwandte_branchen(basis.zielgruppe):
            varianten.append(Variante(VariantenTyp.BRANCHE, branche, basis.region))

        return varianten[: self._max_runden]

    # ----------------------------------------------------------------- Ausführung

    def _sendbar(self) -> int:
        try:
            return int(self._bridge.status_lesen().get("sendable", 0))
        except Exception:
            return 0

    def _variante_auftrag(self, variante: Variante, restmenge: int) -> Auftrag:
        """Baut einen bestätigten Such-Auftrag für eine Variante.

        Restmenge: wie viele noch fehlen — die Engine sucht gezielt nur den Rest
        (plus Puffer), nicht jedes Mal die volle Zielmenge.
        """
        menge = max(10, restmenge + 10)   # kleiner Puffer für Qualitätsausfall
        auftrag = Auftrag(
            zielgruppe=variante.zielgruppe,
            region=variante.region,
            lead_anzahl=menge,
            angebot="(Target Fill)",
            qualitaet=Qualitaetskriterien(),
            erlaubte_aktion=ErlaubteAktion.SUCHEN_AUFBEREITEN,
        )
        auftrag.bestaetigen()
        return auftrag

    def fuelle(
        self,
        basis: Auftrag,
        fortschritt: Optional[FortschrittFn] = None,
    ) -> TargetFillBericht:
        """Führt die mehrrundige Auffüllung aus.

        basis: der bestätigte Original-Auftrag (lead_anzahl = Zielwert).
        fortschritt: optionaler Callback nach jeder Runde (für Live-Updates).
        """
        ziel = basis.lead_anzahl
        varianten = self.plane_varianten(basis)
        start_sendbar = self._sendbar()
        sendbar = start_sendbar

        runden: list[RundenErgebnis] = []
        leere_in_folge = 0
        abbruch = AbbruchGrund.VARIANTEN_DURCH

        for i, variante in enumerate(varianten, start=1):
            # Ziel schon erreicht? Vor jeder Runde prüfen.
            if sendbar >= ziel:
                abbruch = AbbruchGrund.ZIEL_ERREICHT
                break

            vorher = sendbar
            restmenge = ziel - sendbar

            try:
                auftrag = self._variante_auftrag(variante, restmenge)
                self._bridge.suchen(auftrag)
                nachher = self._sendbar()
                ergebnis = RundenErgebnis(
                    runde=i, variante=variante,
                    sendbar_vorher=vorher, sendbar_nachher=nachher,
                )
            except Exception as exc:
                ergebnis = RundenErgebnis(
                    runde=i, variante=variante,
                    sendbar_vorher=vorher, sendbar_nachher=vorher,
                    fehler=str(exc),
                )

            runden.append(ergebnis)
            sendbar = ergebnis.sendbar_nachher

            if fortschritt:
                try:
                    fortschritt(i, len(varianten), ergebnis)
                except Exception:
                    pass

            # Erschöpfungs-Erkennung: zu wenig Zuwachs in Folge
            if ergebnis.zuwachs < self._erschoepft_schwelle:
                leere_in_folge += 1
                if leere_in_folge >= self._erschoepft_runden:
                    abbruch = AbbruchGrund.ERSCHOEPFT
                    break
            else:
                leere_in_folge = 0

            # Harte Obergrenze
            if i >= self._max_runden:
                abbruch = AbbruchGrund.MAX_RUNDEN
                break
        else:
            # Schleife normal durchgelaufen (kein break)
            abbruch = (
                AbbruchGrund.ZIEL_ERREICHT if sendbar >= ziel
                else AbbruchGrund.VARIANTEN_DURCH
            )

        # Falls die letzte Runde das Ziel erreichte
        if sendbar >= ziel:
            abbruch = AbbruchGrund.ZIEL_ERREICHT

        return TargetFillBericht(
            ziel=ziel,
            start_sendbar=start_sendbar,
            end_sendbar=sendbar,
            abbruch_grund=abbruch,
            runden=runden,
        )

    # ----------------------------------------------------------------- Bericht

    @staticmethod
    def bericht_text(b: TargetFillBericht) -> str:
        """Kundenfähiger Abschlussbericht über alle Runden."""
        zeilen = []

        if b.ziel_erreicht:
            zeilen.append(f"🎉 Ziel erreicht: {b.end_sendbar}/{b.ziel} saubere Leads!\n")
        elif b.abbruch_grund == AbbruchGrund.ERSCHOEPFT:
            zeilen.append(
                f"✅ Auffüllung abgeschlossen: {b.end_sendbar}/{b.ziel} saubere Leads.\n"
                f"Die Zielgruppe ist in den durchsuchten Gebieten ausgeschöpft.\n"
            )
        else:
            zeilen.append(f"✅ Auffüllung abgeschlossen: {b.end_sendbar}/{b.ziel} saubere Leads.\n")

        zeilen.append(f"📈 In dieser Auffüllung gewonnen: +{b.gewonnen}")
        zeilen.append(f"🔄 Durchsuchte Varianten: {len(b.runden)}\n")

        # Runden-Detail (kompakt)
        for r in b.runden:
            pfeil = f"+{r.zuwachs}" if r.zuwachs > 0 else "±0"
            fehler = f"  ⚠️ {r.fehler[:40]}" if r.fehler else ""
            zeilen.append(f"   {r.runde}. {r.variante.beschreibung()}: {pfeil}{fehler}")

        if not b.ziel_erreicht:
            zeilen.append(f"\n⚠️  Es fehlen noch {b.fehlend} zum Ziel.")
            if b.abbruch_grund == AbbruchGrund.ERSCHOEPFT:
                zeilen.append(
                    "Mehr saubere Leads dieser Art gibt es in diesen Regionen kaum noch.\n"
                    "Möglich: andere Zielgruppe oder Qualitätskriterien anpassen."
                )

        zeilen.append("\n👉 Sag mir, wenn du die Leads sehen oder die Mail-Vorschau öffnen willst.")
        return "\n".join(zeilen)
