"""Hermes Sales Operator — Kunden-Telegram-Bot.

Einstiegspunkt: python bot.py  (oder über start_operator.bat)

Bedienung:
  Kunde schreibt normal: "Such mir 100 Handwerker in NRW für Website"
  Operator antwortet auf Deutsch, holt Bestätigung, startet dann die Suche.

Keine /commands mit |-Syntax. Keine Admin-Funktionen im Kundenfluss.
Keine .env-Datei wird gelesen. Config kommt aus product_config.json.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# --- Eigene Module ---
_PRODUCT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PRODUCT_ROOT))

# TelegramAPI aus dem bestehenden telegram_seller (unverändert)
_TG_SELLER = _PRODUCT_ROOT / "b2bbot" / "telegram_seller"
sys.path.insert(0, str(_TG_SELLER))

from tg_api import TelegramAPI  # noqa: E402 (aus b2bbot/telegram_seller)

from product.agent.runner import AgentRunner
from product.bridge.engine_bridge import EngineBridge, EngineError
from product.operator.confirm import ConfirmGate
from product.operator.intake import OperatorIntake
from product.operator.llm_anthropic import build_anthropic_llm
from product.operator.reporter import Reporter
from product.telegram.config import laden as config_laden
from product.telegram.dialog import DialogManager

_LOCK_DATEI = Path(__file__).parent / "operator.lock"

HILFE_TEXT = """\
Hermes Sales Operator

Schreib mir einfach, was du suchst — ganz normal:
  "Such 100 Handwerker in NRW, ich verkaufe Websites"
  "50 IT-Dienstleister in München für SEO"

Ich verstehe dich, frage nach wenn etwas fehlt, und
starte die Suche erst nach deiner Bestätigung.

Befehle:
  /status   — aktueller Auftragsstatus
  /hilfe    — diese Nachricht
"""


def _lock_pruefen() -> None:
    if _LOCK_DATEI.exists():
        try:
            alter_pid = int(_LOCK_DATEI.read_text().strip())
            import subprocess
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {alter_pid}"],
                capture_output=True, text=True,
            ).stdout
            if str(alter_pid) in out and "python" in out.lower():
                print(f"FEHLER: Bot läuft bereits (PID {alter_pid}). Abbruch.")
                sys.exit(1)
        except (ValueError, OSError):
            pass
    _LOCK_DATEI.write_text(str(os.getpid()))


def _lock_freigeben() -> None:
    try:
        _LOCK_DATEI.unlink(missing_ok=True)
    except Exception:
        pass


def _verarbeite_update(upd: dict, tg: TelegramAPI, cfg, mgr: DialogManager) -> None:
    msg = upd.get("message") or upd.get("edited_message")
    if not msg:
        return

    chat_id = str(msg["chat"]["id"])
    text = (msg.get("text") or "").strip()
    if not text:
        return

    # Owner-Lock: nur der konfigurierte Besitzer darf den Bot bedienen
    if cfg.owner_chat_id and chat_id != cfg.owner_chat_id:
        tg.try_send(chat_id, "Dieser Bot ist privat.")
        return

    # Einmalige Owner-Registrierung (erster Start ohne owner_chat_id in Config)
    if not cfg.owner_chat_id:
        _owner_registrieren(cfg, chat_id)

    # --- Systemkommandos ---
    low = text.lower()
    if low in ("/start", "/hilfe", "/help"):
        tg.try_send(chat_id, HILFE_TEXT)
        return

    if low == "/status":
        tg.try_send(chat_id, mgr.status_text(chat_id))
        return

    # --- Dialog (normaler Text / natürliche Sprache) ---
    mgr.verarbeite(chat_id, text)


def _owner_registrieren(cfg, chat_id: str) -> None:
    """Speichert die erste Chat-ID als Owner, falls noch keine gesetzt."""
    import json
    from product.telegram.config import _CONFIG_PFAD_DEFAULT
    pfad = _CONFIG_PFAD_DEFAULT
    try:
        d = json.loads(pfad.read_text(encoding="utf-8"))
        d["owner_chat_id"] = chat_id
        pfad.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        cfg.owner_chat_id = chat_id
        print(f"[bot] Owner registriert: {chat_id}")
    except Exception as e:
        print(f"[bot] Owner konnte nicht gespeichert werden: {e}")


def main() -> None:
    _lock_pruefen()

    print("[boot] Hermes Sales Operator startet…")

    # --- Config laden ---
    try:
        cfg = config_laden()
    except (FileNotFoundError, ValueError) as e:
        print(f"[boot] FEHLER: {e}")
        _lock_freigeben()
        sys.exit(1)

    # --- Datenverzeichnisse anlegen ---
    cfg.orders_dir.mkdir(parents=True, exist_ok=True)
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)

    # --- Bridge prüfen ---
    try:
        bridge = EngineBridge(cfg.engine_dir)
        print(f"[boot] Engine gefunden: {cfg.engine_dir}")
    except EngineError as e:
        print(f"[boot] FEHLER Engine: {e}")
        _lock_freigeben()
        sys.exit(1)

    # --- Telegram ---
    tg = TelegramAPI(cfg.bot_token)
    me = tg.get_me()
    if not me.get("ok"):
        print("[boot] FEHLER: Telegram-Token ungültig oder keine Verbindung.")
        _lock_freigeben()
        sys.exit(1)
    bot_name = me["result"].get("username", "?")
    print(f"[bot] Gestartet als @{bot_name}")

    # --- Operator-Kern ---
    llm = build_anthropic_llm(cfg.anthropic_api_key or None)
    if llm:
        print("[bot] LLM-Unterstützung aktiv (Anthropic).")
    else:
        print("[bot] Kein API-Key — deterministischer Parser aktiv.")

    intake = OperatorIntake(llm_fn=llm)
    gate = ConfirmGate()

    # Agent als Aufsatz: führt bestätigte Aufträge eigenständig (suchen + auffüllen,
    # Stopp am harten Tor). Sendet nie selbst. Ohne Key arbeitet er deterministisch.
    agent_runner = AgentRunner(
        bridge=bridge,
        data_dir=cfg.data_dir,
        reporter=Reporter(bridge.engine_dir),
        api_key=cfg.anthropic_api_key or None,
    )
    print("[bot] Agent-Modus aktiv — Aufträge werden eigenständig geführt.")

    mgr = DialogManager(
        intake=intake,
        gate=gate,
        bridge=bridge,
        orders_dir=cfg.orders_dir,
        send_fn=lambda cid, txt: tg.try_send(cid, txt),
        agent_runner=agent_runner,
    )

    print("[bot] Bereit. Warte auf Nachrichten…")

    offset = 0
    try:
        while True:
            try:
                updates = tg.get_updates(offset, timeout=50)
            except Exception as exc:
                print(f"[bot] getUpdates Fehler: {exc}; retry in 5s")
                time.sleep(5)
                continue

            for upd in updates:
                offset = upd["update_id"] + 1
                try:
                    _verarbeite_update(upd, tg, cfg, mgr)
                except Exception as exc:
                    print(f"[bot] Update-Fehler (ignoriert): {exc}")

    except KeyboardInterrupt:
        print("\n[bot] Gestoppt.")
    finally:
        _lock_freigeben()


if __name__ == "__main__":
    main()
