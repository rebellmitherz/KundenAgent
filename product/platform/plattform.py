"""Plattform-Orchestrierung — pro Mandant ein isolierter Akquise-Agent (F4).

Baut auf dem Mandanten-Register (F3) auf und macht die Plattform „lebendig":
für jeden Mandanten wird bei Bedarf eine eigene, hart isolierte Laufzeit
gebaut — eigene EngineBridge (engine_dir des Mandanten) und ein eigener
AgentRunner (eigenes, abgeleitetes data_dir). Beide existieren bereits und sind
über engine_dir/data_dir parametrisiert — hier werden sie nur je Mandant
zusammengesteckt und gecacht. Bestehende Logik wird NICHT eingeschränkt.

Zusätzlich:
  - Telegram-Routing: eingehende Nachricht → richtiger Mandant (per owner_chat_id).
  - PlattformWatcher: ein Watcher je aktivem Mandant, jeder meldet an SEINEN
    owner_chat_id (kein Datenleck zwischen Kunden).

Testbar ohne echte Engine: bridge_factory/reporter_factory sind injizierbar.
"""
from __future__ import annotations

from typing import Callable, Optional

from product.agent.runner import AgentRunner
from product.agent.watcher import Watcher
from product.bridge.engine_bridge import EngineBridge, EngineError
from product.platform.mandant import Mandant, MandantenFehler, MandantenRegister

BridgeFactory = Callable[[str], object]      # (engine_dir) -> Bridge
ReporterFactory = Callable[[str], object]    # (engine_dir) -> Reporter
SendFn = Callable[[str, str], None]          # (chat_id, text) -> None


def _default_reporter_factory(engine_dir: str):
    # Lazy-Import, damit Tests die Plattform ohne Reporter/Engine nutzen können.
    from product.operator.reporter import Reporter
    return Reporter(engine_dir)


class Plattform:
    """Verwaltet die Laufzeit aller Mandanten (Runner/Bridge je Kunde, gecacht)."""

    def __init__(
        self,
        register: MandantenRegister,
        *,
        api_key_default: str = "",
        bridge_factory: Optional[BridgeFactory] = None,
        reporter_factory: Optional[ReporterFactory] = None,
        max_schritte: int = 12,
    ):
        self._register = register
        self._api_key_default = api_key_default or ""
        self._bridge_factory = bridge_factory or (lambda ed: EngineBridge(ed))
        self._reporter_factory = reporter_factory or _default_reporter_factory
        self._max_schritte = max_schritte
        self._runners: dict[str, AgentRunner] = {}

    @property
    def register(self) -> MandantenRegister:
        return self._register

    # ----------------------------------------------------------------- Routing

    def mandant_fuer_chat(self, chat_id: str) -> Optional[Mandant]:
        """Telegram-Routing: welcher Mandant gehört zu dieser Chat-ID?"""
        return self._register.per_owner(chat_id)

    # ----------------------------------------------------------------- Bauen

    def runner_fuer(self, mandant_id: str) -> AgentRunner:
        """Liefert den (gecachten) isolierten Runner eines Mandanten.

        Wirft MandantenFehler bei unbekanntem Mandanten und EngineError, wenn
        dessen Engine (engine_dir) noch nicht eingerichtet ist.
        """
        mandant = self._register.holen(mandant_id)
        if mandant is None:
            raise MandantenFehler(f"Unbekannter Mandant '{mandant_id}'.")

        mid = mandant.mandant_id
        cached = self._runners.get(mid)
        if cached is not None:
            return cached

        if not mandant.engine_dir:
            raise EngineError(
                f"Mandant '{mid}' hat keine Engine (engine_dir) — noch nicht eingerichtet."
            )

        bridge = self._bridge_factory(mandant.engine_dir)
        try:
            reporter = self._reporter_factory(mandant.engine_dir)
        except Exception:
            reporter = None  # Reporter optional — Runner fällt auf Bridge-Status zurück

        runner = AgentRunner(
            bridge=bridge,
            data_dir=self._register.data_dir_fuer(mid),
            reporter=reporter,
            api_key=(mandant.anthropic_api_key or self._api_key_default or None),
            max_schritte=self._max_schritte,
        )
        self._runners[mid] = runner
        return runner

    def runner_oder_none(self, mandant_id: str) -> Optional[AgentRunner]:
        """Wie runner_fuer, aber None statt Ausnahme (für Iteration über alle)."""
        try:
            return self.runner_fuer(mandant_id)
        except Exception:
            # unbekannt / Engine nicht eingerichtet / Bau fehlgeschlagen
            return None

    def betriebsbereit(self, mandant_id: str) -> bool:
        """True, wenn der Mandant eine baubare, isolierte Laufzeit hat."""
        return self.runner_oder_none(mandant_id) is not None

    def aktive_runner(self) -> list[tuple[Mandant, AgentRunner]]:
        """Alle aktiven, betriebsbereiten Mandanten mit ihrem Runner.

        Nicht eingerichtete Mandanten (keine Engine) werden still übersprungen —
        der Rest der Plattform läuft trotzdem weiter."""
        out: list[tuple[Mandant, AgentRunner]] = []
        for m in self._register.alle(nur_aktive=True):
            runner = self.runner_oder_none(m.mandant_id)
            if runner is not None:
                out.append((m, runner))
        return out

    def invalidieren(self, mandant_id: str) -> None:
        """Verwirft den gecachten Runner (z. B. nach Config-Änderung)."""
        from product.platform.mandant import slugify
        self._runners.pop(slugify(mandant_id), None)


class PlattformWatcher:
    """Ein Watcher je aktivem Mandant — jeder meldet an SEINEN owner_chat_id.

    So bekommt jeder Kunde nur seine eigenen Signale (Termine, Tore, Nachfassen);
    es gibt keinen Querverkehr zwischen Mandanten.
    """

    def __init__(
        self,
        plattform: Plattform,
        send_fn: SendFn,
        intervall_sek: int = 300,
        auto_abruf: bool = True,
    ):
        self._plattform = plattform
        self._send = send_fn
        self._intervall = intervall_sek
        self._auto_abruf = auto_abruf
        self._watchers: dict[str, Watcher] = {}

    def _aufbauen(self) -> None:
        """Erzeugt/aktualisiert die Watcher-Menge passend zu den aktiven Mandanten."""
        aktiv_ids = set()
        for mandant, runner in self._plattform.aktive_runner():
            if not mandant.owner_chat_id:
                continue  # ohne Ziel-Chat kein Watcher
            aktiv_ids.add(mandant.mandant_id)
            if mandant.mandant_id not in self._watchers:
                self._watchers[mandant.mandant_id] = Watcher(
                    runner=runner,
                    owner_chat_id=mandant.owner_chat_id,
                    send_fn=self._send,
                    intervall_sek=self._intervall,
                    auto_abruf=self._auto_abruf,
                )
        # Watcher entfernter/deaktivierter Mandanten stoppen
        for mid in list(self._watchers):
            if mid not in aktiv_ids:
                self._watchers.pop(mid).stop()

    def starten(self) -> None:
        self._aufbauen()
        for w in self._watchers.values():
            w.starten()

    def stop(self) -> None:
        for w in self._watchers.values():
            w.stop()

    def jetzt_pruefen(self) -> dict[str, list[str]]:
        """Sofort-Check über alle Mandanten — gibt je Mandant die gesendeten
        Meldungstexte zurück (für Tests/Debug)."""
        self._aufbauen()
        return {mid: w.jetzt_pruefen() for mid, w in self._watchers.items()}

    @property
    def watcher(self) -> dict[str, Watcher]:
        return self._watchers
