"""Watcher — periodischer Hintergrund-Thread für Push-Meldungen (Phase D).

Prüft alle `intervall_sek` Sekunden den Stand und sendet neue Meldungen
via Telegram an den Besitzer. Läuft als Daemon-Thread neben dem Bot.

Sicherheitsgarantien:
  - Sendet KEINE Lead-Mails — nur Telegram-Meldungen an den Besitzer.
  - Dedupliziert: jede Signatur wird nur einmal gesendet (kein Spam).
  - Absturzsicher: Fehler werden geloggt, Loop läuft weiter.
  - Sauber stoppbar via stop().
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from product.agent.notifier import meldungen_ermitteln
from product.agent.runner import AgentRunner

SendFn = Callable[[str, str], None]   # (chat_id, text) -> None


class Watcher:
    """Startet als Daemon-Thread und schickt Push-Meldungen wenn nötig."""

    def __init__(
        self,
        runner: AgentRunner,
        owner_chat_id: str,
        send_fn: SendFn,
        intervall_sek: int = 300,      # 5 Minuten Standard
    ):
        self._runner       = runner
        self._owner        = owner_chat_id
        self._send         = send_fn
        self._intervall    = intervall_sek
        self._stop_evt     = threading.Event()
        self._gesendete_signaturen: set[str] = set()
        self._thread: Optional[threading.Thread] = None

    def starten(self) -> None:
        """Startet den Hintergrund-Thread. Idempotent."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()

    def jetzt_pruefen(self) -> list[str]:
        """Sofortiger Check — gibt gesendete Meldungstexte zurück (für Tests/Debug)."""
        return self._pruefen_und_senden()

    # ----------------------------------------------------------------- intern

    def _loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                self._pruefen_und_senden()
            except Exception as exc:
                print(f"[watcher] Fehler (ignoriert): {exc}")
            self._stop_evt.wait(self._intervall)

    def _pruefen_und_senden(self) -> list[str]:
        try:
            laeufe           = self._runner.laeufe()
            antworten        = self._runner.antworten()
            nachfass_faellig = self._runner.nachfass_faellig()
        except Exception:
            return []

        meldungen = meldungen_ermitteln(
            laeufe=laeufe,
            antworten=antworten,
            nachfass_faellig=nachfass_faellig,
            gesendete_signaturen=self._gesendete_signaturen,
        )

        gesendete_texte: list[str] = []
        for m in meldungen:
            try:
                self._send(self._owner, m.text)
                self._gesendete_signaturen.add(m.signatur)
                gesendete_texte.append(m.text)
            except Exception as exc:
                print(f"[watcher] Senden fehlgeschlagen: {exc}")

        return gesendete_texte
