"""Zugangs- und Mandanten-Routing für den Live-Bot (F7a).

Der Bot ist ab F7 mehrmandantenfähig. Diese Schicht entscheidet ausschließlich,
*welche* Laufzeit eine eingehende Telegram-Nachricht bedienen darf — sie kennt
keine Befehle und sendet nichts. So bleibt `bot.py` schlank und die Routing-Logik
ist ohne Telegram/Engine voll testbar.

Zwei Betriebsarten:

  Single-Tenant (kein aktiver Mandant registriert) — Verhalten EXAKT wie vor F7:
    Genau eine Laufzeit (``single_sitzung``). Der erste Chat wird als Owner
    registriert; danach darf nur dieser Owner den Bot bedienen ("privat").

  Multi-Tenant (mind. 1 aktiver Mandant):
    Eingehende Chat-ID → Mandant (über ``owner_chat_id``). Jeder Mandant hat
    seine eigene, isolierte Laufzeit (eigener Runner + eigener Dialog). Eine
    unbekannte Chat-ID wird höflich abgelehnt — NICHT bedient. Der Betreiber
    (``operator_chat_id``) darf zusätzlich die Plattform-Gesamtsicht abrufen.

Es gibt nie Querverkehr zwischen Mandanten: jede Chat-ID landet höchstens in
genau einer Sitzung.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class Sitzung:
    """Eine bedienbare Laufzeit: eigener Agent-Runner + eigener Dialog-Manager.

    runner/mgr sind absichtlich generisch (duck-typed), damit Tests Mocks
    einsetzen können. ``betriebsbereit=False`` bedeutet: Mandant existiert, ist
    aber noch nicht eingerichtet (keine Engine) — er wird nicht bedient.
    """
    runner: object = None
    mgr: object = None
    name: str = ""
    betriebsbereit: bool = True


@dataclass
class Zugang:
    """Ergebnis der Routing-Entscheidung für eine Chat-ID.

    sitzung:      bedienbare Laufzeit (oder None, wenn nicht bedient wird).
    ist_operator: True, wenn der Chat der Plattform-Betreiber ist (darf
                  zusätzlich Operator-Befehle wie /plattform nutzen).
    ablehnung:    höflicher Text, falls der Chat NICHT bedient wird (sonst None).
    """
    sitzung: Optional[Sitzung] = None
    ist_operator: bool = False
    ablehnung: Optional[str] = None


# Texte zentral, damit Verhalten/Tests stabil bleiben.
PRIVAT_TEXT = "Dieser Bot ist privat."
NICHT_FREIGESCHALTET_TEXT = (
    "Dieser Zugang ist nicht freigeschaltet. "
    "Bitte wende dich an deinen Ansprechpartner."
)
IN_EINRICHTUNG_TEXT = (
    "Dein Zugang wird gerade eingerichtet — "
    "ich melde mich, sobald alles bereit ist."
)


class Router:
    """Leitet eine eingehende Chat-ID an die richtige Sitzung (oder lehnt ab).

    Parameter:
      single_sitzung:   gesetzt ⇒ Single-Tenant-Modus (genau diese eine Sitzung).
      plattform:        gesetzt ⇒ Multi-Tenant-Modus (Routing über die Plattform).
                        Erwartet ``mandant_fuer_chat(chat_id)``.
      operator_chat_id: Chat des Plattform-Betreibers (für /plattform).
      sitzung_factory:  (mandant) -> Sitzung — baut/holt die Laufzeit eines
                        Mandanten (gecacht). Nur im Multi-Tenant-Modus genutzt.
      owner_registrieren: optional (chat_id) -> None — wird im Single-Tenant-Modus
                        beim allerersten Chat aufgerufen, um den Owner zu setzen.
    """

    def __init__(
        self,
        *,
        single_sitzung: Optional[Sitzung] = None,
        plattform: object = None,
        operator_chat_id: str = "",
        sitzung_factory: Optional[Callable[[object], Optional[Sitzung]]] = None,
        owner_registrieren: Optional[Callable[[str], None]] = None,
    ):
        if single_sitzung is None and plattform is None:
            raise ValueError("Router braucht entweder single_sitzung oder plattform.")
        self._single = single_sitzung
        self._plattform = plattform
        self._operator = (operator_chat_id or "").strip()
        self._factory = sitzung_factory
        self._owner_reg = owner_registrieren
        self._cache: dict[str, Sitzung] = {}

    @property
    def multi(self) -> bool:
        """True im Multi-Tenant-Modus."""
        return self._single is None

    def aufloesen(self, chat_id) -> Zugang:
        """Entscheidet, ob/wie diese Chat-ID bedient wird."""
        chat_id = str(chat_id)
        if not self.multi:
            return self._aufloesen_single(chat_id)
        return self._aufloesen_multi(chat_id)

    # ----------------------------------------------------------------- intern

    def _aufloesen_single(self, chat_id: str) -> Zugang:
        op = self._operator
        if not op:
            # Allererster Start ohne Owner: dieser Chat wird Owner und wird bedient.
            if self._owner_reg:
                self._owner_reg(chat_id)
            self._operator = chat_id
            return Zugang(sitzung=self._single, ist_operator=True)
        if chat_id != op:
            return Zugang(ablehnung=PRIVAT_TEXT)
        # Owner darf bedienen; ist im Single-Tenant zugleich „Operator".
        return Zugang(sitzung=self._single, ist_operator=True)

    def _aufloesen_multi(self, chat_id: str) -> Zugang:
        ist_op = bool(self._operator) and chat_id == self._operator

        mandant = self._plattform.mandant_fuer_chat(chat_id)
        if mandant is not None:
            sitzung = self._cache.get(mandant.mandant_id)
            if sitzung is None and self._factory is not None:
                sitzung = self._factory(mandant)
                # NUR betriebsbereite Sitzungen cachen. Ein noch nicht
                # eingerichteter Mandant (Engine kommt evtl. später) wird beim
                # nächsten Versuch erneut gebaut — sonst bliebe er bis zum
                # Neustart fälschlich "in Einrichtung".
                if sitzung is not None and sitzung.betriebsbereit:
                    self._cache[mandant.mandant_id] = sitzung
            if sitzung is None or not sitzung.betriebsbereit:
                return Zugang(ist_operator=ist_op, ablehnung=IN_EINRICHTUNG_TEXT)
            return Zugang(sitzung=sitzung, ist_operator=ist_op)

        # Keine Mandanten-Zuordnung: nur der Betreiber darf (Operator-Befehle).
        if ist_op:
            return Zugang(ist_operator=True)
        return Zugang(ablehnung=NICHT_FREIGESCHALTET_TEXT)

    def invalidieren(self, mandant_id: str) -> None:
        """Verwirft eine gecachte Mandanten-Sitzung (z. B. nach Config-Änderung)."""
        self._cache.pop(mandant_id, None)
