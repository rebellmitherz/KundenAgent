"""Dialog-Zustandsmaschine für den Kunden-Telegram-Bot.

Verwaltet den gesamten Gesprächsfluss pro Chat-ID:
  IDLE → INTAKE_RÜCKFRAGE → CONFIRMING → RUNNING → IDLE

Zustandsübergänge:
  IDLE / INTAKE_RÜCKFRAGE:
    Text → intake.verstehe()
      → unvollständig → Rückfrage senden, Kontext speichern → INTAKE_RÜCKFRAGE
      → vollständig   → Bestätigungsfrage senden            → CONFIRMING

  CONFIRMING:
    Text → gate.verarbeite_antwort()
      → BESTAETIGT → Suche starten (Hintergrund-Thread)     → RUNNING
      → ABGELEHNT  → Zustand löschen                         → IDLE
      → KORREKTUR  → Auftrag anpassen, erneut fragen          → CONFIRMING
      → UNKLAR     → Rückfrage senden                         → CONFIRMING

  RUNNING:
    Text → "Suche läuft noch…"
    (Hintergrund-Thread meldet sich wenn fertig)             → IDLE
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import re

if TYPE_CHECKING:
    from product.agent.runner import AgentRunner

from product.bridge.engine_bridge import EngineBridge, EngineBrueckenErgebnis
from product.operator.confirm import ConfirmGate, ConfirmStatus
from product.operator.intake import OperatorIntake
from product.operator.order_schema import Auftrag, AuftragsStatus, Ergebnis
from product.operator.reporter import Reporter
from product.operator.target_fill import TargetFillManager


class DialogModus(str, Enum):
    IDLE                = "idle"
    INTAKE_RÜCKFRAGE    = "intake_rückfrage"
    CONFIRMING          = "confirming"
    RUNNING             = "running"


@dataclass
class ChatZustand:
    modus: DialogModus = DialogModus.IDLE
    intake_kontext: dict = field(default_factory=dict)
    auftrag: Optional[Auftrag] = None
    # Letzter abgeschlossener Auftrag unter Ziel → ermöglicht "füll auf" als Folgebefehl
    letzter_auftrag: Optional[Auftrag] = None
    letzter_fehlend: int = 0


# Erkennt "weiter / füll auf / mehr" als Auffüll-Befehl
_FUELL_MUSTER = re.compile(
    r"\b(füll|fuell|auffüll|auffuell|weiter|mehr|nachlegen|aufstocken|"
    r"weitermachen|fortsetzen|nachschieben|nachfüllen|nachfuellen)\b",
    re.IGNORECASE,
)


# Callback-Typ: send_fn(chat_id, text) → None
SendFn = Callable[[str, str], None]


class DialogManager:
    """Verwaltet den Dialog-Zustand aller Chats. Thread-sicher."""

    def __init__(
        self,
        intake: OperatorIntake,
        gate: ConfirmGate,
        bridge: EngineBridge,
        orders_dir: Path,
        send_fn: Optional[SendFn] = None,
        agent_runner: "Optional[AgentRunner]" = None,
    ):
        self._intake = intake
        self._gate = gate
        self._bridge = bridge
        self._orders_dir = orders_dir
        self._reporter = Reporter(bridge.engine_dir)
        self._target_fill = TargetFillManager(bridge)
        self._send_fn = send_fn
        # Optionaler Agent: wenn gesetzt, führt ein bestätigter Auftrag durch den
        # Agent-Loop (suchen + selbst auffüllen, Stopp am harten Tor) statt der
        # reinen Einzel-Suche. Ohne ihn bleibt das Verhalten exakt wie bisher.
        self._agent_runner = agent_runner
        self._zustaende: dict[str, ChatZustand] = {}
        self._lock = threading.Lock()

    def set_send_fn(self, fn: SendFn) -> None:
        self._send_fn = fn

    def _zustand(self, chat_id: str) -> ChatZustand:
        with self._lock:
            if chat_id not in self._zustaende:
                self._zustaende[chat_id] = ChatZustand()
            return self._zustaende[chat_id]

    def _sende(self, chat_id: str, text: str) -> None:
        if self._send_fn:
            self._send_fn(chat_id, text)

    def verarbeite(self, chat_id: str, text: str) -> None:
        """Haupteinstieg — verarbeitet eine Kundennachricht."""
        z = self._zustand(chat_id)

        if z.modus == DialogModus.RUNNING:
            self._sende(chat_id,
                "⏳ Die Suche läuft noch im Hintergrund.\n"
                "Ich melde mich automatisch, wenn sie fertig ist.")
            return

        # Auffüll-Befehl ("füll auf", "weiter", "mehr") — nur sinnvoll wenn es
        # einen letzten, nicht erreichten Auftrag gibt und wir im Leerlauf sind.
        if (z.modus == DialogModus.IDLE
                and z.letzter_auftrag is not None
                and z.letzter_fehlend > 0
                and _FUELL_MUSTER.search(text)):
            self._starte_target_fill(chat_id, z)
            return

        if z.modus in (DialogModus.IDLE, DialogModus.INTAKE_RÜCKFRAGE):
            self._handle_intake(chat_id, text, z)
            return

        if z.modus == DialogModus.CONFIRMING:
            self._handle_confirming(chat_id, text, z)
            return

    def status_text(self, chat_id: str) -> str:
        z = self._zustand(chat_id)
        if z.modus == DialogModus.IDLE:
            return "Bereit. Sag mir, was du suchst."
        if z.modus == DialogModus.INTAKE_RÜCKFRAGE:
            felder = [k for k in ["zielgruppe", "region", "lead_anzahl", "angebot"]
                      if not z.intake_kontext.get(k)]
            return f"Auftrag in Aufbau. Noch offen: {', '.join(felder)}"
        if z.modus == DialogModus.CONFIRMING and z.auftrag:
            return f"Warte auf deine Bestätigung:\n{z.auftrag.als_bestaetigung()}"
        if z.modus == DialogModus.RUNNING:
            return "🔎 Suche läuft im Hintergrund…"
        return "Unbekannter Status."

    # --- interne Handler ---

    def _handle_intake(self, chat_id: str, text: str, z: ChatZustand) -> None:
        kontext = z.intake_kontext if z.modus == DialogModus.INTAKE_RÜCKFRAGE else {}
        ergebnis = self._intake.verstehe(text, kontext or None)

        if not ergebnis.vollstaendig:
            with self._lock:
                z.modus = DialogModus.INTAKE_RÜCKFRAGE
                z.intake_kontext = ergebnis.kontext
            self._sende(chat_id, ergebnis.rueckfrage)
            return

        # Auftrag vollständig → Bestätigung einholen
        auftrag = ergebnis.auftrag
        with self._lock:
            z.modus = DialogModus.CONFIRMING
            z.auftrag = auftrag
            z.intake_kontext = {}

        frage = self._gate.frage_stellen(auftrag)
        self._sende(chat_id, "Ich habe deinen Auftrag so verstanden:\n\n" + auftrag.als_bestaetigung() +
                    "\n\nPasst das?\n'Ja, starten' — oder sag, was ich ändern soll.")

    def _handle_confirming(self, chat_id: str, text: str, z: ChatZustand) -> None:
        if not z.auftrag:
            with self._lock:
                z.modus = DialogModus.IDLE
            self._sende(chat_id, "Kein aktiver Auftrag. Sag mir, was du suchst.")
            return

        confirm = self._gate.verarbeite_antwort(text, z.auftrag)

        if confirm.status == ConfirmStatus.BESTAETIGT:
            auftrag = z.auftrag
            with self._lock:
                z.modus = DialogModus.RUNNING

            # Auftrag als Datei speichern (Audit-Trail)
            try:
                auftrag.speichern(self._orders_dir)
            except Exception:
                pass

            # Agent-Modus (wenn verdrahtet) oder klassische Einzel-Suche.
            if self._agent_runner is not None:
                self._sende(chat_id,
                    f"✅ Auftrag bestätigt. Ich übernehme die Kampagne und arbeite "
                    f"selbstständig auf dein Ziel hin.\n\n"
                    f"🎯 {auftrag.zielgruppe} · {auftrag.region} · {auftrag.lead_anzahl} Leads\n\n"
                    f"Ich suche, fülle bei Lücken eigenständig nach und melde mich, "
                    f"sobald deine Entscheidung gefragt ist. 📲")
                arbeiter = self._agent_im_hintergrund
            else:
                self._sende(chat_id,
                    f"✅ Auftrag bestätigt. Suche startet im Hintergrund.\n\n"
                    f"🎯 {auftrag.zielgruppe} · {auftrag.region} · {auftrag.lead_anzahl} Leads\n\n"
                    f"Das dauert 15–30 Min. Ich melde mich automatisch. 📲")
                arbeiter = self._suche_im_hintergrund

            t = threading.Thread(target=arbeiter, args=(chat_id, auftrag), daemon=True)
            t.start()
            return

        if confirm.status == ConfirmStatus.ABGELEHNT:
            with self._lock:
                z.modus = DialogModus.IDLE
                z.auftrag = None
                z.intake_kontext = {}
            self._sende(chat_id,
                "Auftrag verworfen. Sag mir einfach, was du stattdessen suchst.")
            return

        if confirm.status == ConfirmStatus.KORREKTUR:
            self._korrektur_anwenden(chat_id, z, confirm.korrektur_feld, confirm.korrektur_wert)
            return

        # UNKLAR
        self._sende(chat_id, confirm.rueckfrage)

    def _korrektur_anwenden(
        self, chat_id: str, z: ChatZustand, feld: Optional[str], wert: Optional[str]
    ) -> None:
        if not z.auftrag or not feld or wert is None:
            self._sende(chat_id, "Ich konnte die Korrektur nicht verstehen. Was soll ich ändern?")
            return

        a = z.auftrag
        try:
            if feld == "lead_anzahl":
                a.lead_anzahl = int(wert.strip())
            elif feld == "zielgruppe":
                a.zielgruppe = wert.strip()
            elif feld == "region":
                a.region = wert.strip()
            elif feld == "angebot":
                a.angebot = wert.strip()
            else:
                self._sende(chat_id, f"Feld '{feld}' kenne ich nicht. Welches Feld soll ich ändern?")
                return
        except ValueError:
            self._sende(chat_id, f"'{wert}' ist kein gültiger Wert für {feld}.")
            return

        self._sende(chat_id,
            f"Angepasst. Neuer Auftrag:\n\n{a.als_bestaetigung()}\n\n"
            f"Passt das jetzt? 'Ja, starten' oder weitere Änderung?")

    def _agent_im_hintergrund(self, chat_id: str, auftrag: Auftrag) -> None:
        """Lässt den Agenten den Auftrag eigenständig führen (suchen + bei Lücken
        selbst auffüllen), bis ein hartes Tor erreicht ist. Sendet ausschließlich
        den kundenfähigen Abschlusstext — keine Technik, kein Sende-Pfad.
        """
        try:
            ergebnis = self._agent_runner.starten(auftrag)
            self._sende(chat_id, ergebnis.kundentext())
        except Exception as exc:
            self._sende(chat_id,
                "⚠️ Ich musste den Lauf abbrechen und melde mich lieber, "
                "statt etwas Falsches zu tun. Sag mir, wie es weitergehen soll.")
        finally:
            z = self._zustand(chat_id)
            with self._lock:
                z.modus = DialogModus.IDLE
                z.auftrag = None
                # Der Agent füllt selbst auf — kein separater "füll auf"-Folgebefehl.
                z.letzter_auftrag = None
                z.letzter_fehlend = 0

    def _suche_im_hintergrund(self, chat_id: str, auftrag: Auftrag) -> None:
        try:
            ergebnis = self._bridge.suchen(auftrag)

            # Reporter liest echte Engine-Output-Dateien aus
            bericht = self._reporter.text(auftrag)

            fehlend = 0
            if ergebnis.ok:
                rep_daten = self._reporter.bericht(auftrag)
                fehlend = rep_daten.fehlend
                auftrag.abschliessen(Ergebnis(
                    leads_gefunden=rep_daten.run.gefunden,
                    leads_sauber=rep_daten.run.mit_telefon,
                    leads_fehlend=rep_daten.fehlend,
                    zielgruppe_erschoepft=rep_daten.zielgruppe_erschoepft,
                    bericht=bericht,
                ))
                # Bei verfehltem Ziel: Auffüllen anbieten
                if fehlend > 0:
                    bericht += (
                        f"\n\n🎯 Ich kann automatisch auf dein Ziel von "
                        f"{auftrag.lead_anzahl} auffüllen — über angrenzende Regionen "
                        f"und verwandte Branchen.\n"
                        f"Schreib einfach 'füll auf' oder 'weiter'."
                    )
            else:
                auftrag.fehler_setzen(ergebnis.meldung)
                bericht = f"⚠️ Suche meldete einen Fehler:\n{ergebnis.meldung[-400:]}"

            try:
                auftrag.speichern(self._orders_dir)
            except Exception:
                pass

            self._sende(chat_id, bericht)

        except Exception as exc:
            self._sende(chat_id, f"⚠️ Suche abgebrochen: {exc}")
            fehlend = 0

        finally:
            z = self._zustand(chat_id)
            with self._lock:
                z.modus = DialogModus.IDLE
                z.auftrag = None
                # Auftrag für mögliches Auffüllen merken
                if fehlend > 0:
                    z.letzter_auftrag = auftrag
                    z.letzter_fehlend = fehlend
                else:
                    z.letzter_auftrag = None
                    z.letzter_fehlend = 0

    def _starte_target_fill(self, chat_id: str, z: ChatZustand) -> None:
        """Startet die mehrrundige Auffüllung im Hintergrund."""
        basis = z.letzter_auftrag
        if basis is None:
            self._sende(chat_id, "Es gibt gerade keinen Auftrag zum Auffüllen.")
            return

        with self._lock:
            z.modus = DialogModus.RUNNING

        self._sende(chat_id,
            f"🎯 Auffüllen gestartet: Ziel {basis.lead_anzahl} Leads.\n"
            f"Ich durchsuche angrenzende Regionen und verwandte Branchen —\n"
            f"Qualität bleibt Pflicht (Telefon, keine Dubletten).\n"
            f"Das kann je nach Lücke dauern. Ich melde mich nach jeder Runde. 📲")

        t = threading.Thread(
            target=self._target_fill_im_hintergrund,
            args=(chat_id, basis),
            daemon=True,
        )
        t.start()

    def _target_fill_im_hintergrund(self, chat_id: str, basis: Auftrag) -> None:
        def fortschritt(runde: int, gesamt: int, erg) -> None:
            self._sende(chat_id,
                f"   Runde {runde}/{gesamt}: {erg.variante.beschreibung()} "
                f"→ +{erg.zuwachs} (jetzt {erg.sendbar_nachher})")

        try:
            # Basis muss bestätigt sein, damit Varianten sauber abgeleitet werden
            if basis.status == AuftragsStatus.ENTWURF:
                basis.bestaetigen()
            bericht_obj = self._target_fill.fuelle(basis, fortschritt)
            self._sende(chat_id, self._target_fill.bericht_text(bericht_obj))
            verbleibend = bericht_obj.fehlend
        except Exception as exc:
            self._sende(chat_id, f"⚠️ Auffüllen abgebrochen: {exc}")
            verbleibend = 0

        finally:
            z = self._zustand(chat_id)
            with self._lock:
                z.modus = DialogModus.IDLE
                # Nur weiter anbieten wenn noch Lücke UND nicht erschöpft
                if verbleibend > 0:
                    z.letzter_fehlend = verbleibend
                else:
                    z.letzter_auftrag = None
                    z.letzter_fehlend = 0
