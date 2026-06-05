"""Rebellsystem Sales Operator — Kunden-Telegram-Bot.

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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from product.agent.runner import AgentRunner
    from product.closer.closer_adapter import CloserAdapter

# --- Eigene Module ---
_PRODUCT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PRODUCT_ROOT))

# TelegramAPI aus dem bestehenden telegram_seller (unverändert)
_TG_SELLER = _PRODUCT_ROOT / "b2bbot" / "telegram_seller"
sys.path.insert(0, str(_TG_SELLER))

from tg_api import TelegramAPI  # noqa: E402 (aus b2bbot/telegram_seller)

from product.agent.replies import antwort_detail_bericht, termin_detail_bericht
from product.agent.runner import AgentRunner
from product.agent.watcher import Watcher
from product.bridge.engine_bridge import EngineBridge, EngineError
from product.closer.closer_adapter import CloserAdapter
from product.operator.confirm import ConfirmGate
from product.operator.intake import OperatorIntake
from product.operator.llm_anthropic import build_anthropic_llm
from product.operator.reporter import Reporter
from product.telegram.config import laden as config_laden
from product.telegram.dialog import DialogManager

_LOCK_DATEI = Path(__file__).parent / "operator.lock"

HILFE_TEXT = """\
Rebellsystem Sales Operator

Schreib mir einfach, was du suchst — ganz normal:
  "Such 100 Handwerker in NRW, ich verkaufe Websites"
  "50 IT-Dienstleister in München für SEO"

Ich verstehe dich, frage nach wenn etwas fehlt, und
starte die Suche erst nach deiner Bestätigung.

Befehle:
  /status              — Status + Kampagnen-Überblick
  Antworten abrufen    — Postfach jetzt prüfen (hole ich sonst alle 5 Min selbst)
  Antworten            — Überblick eingegangener Antworten
  Mail zeigen          — volle Antworten (auf welche Mail + Text)
  Termin aufbereiten   — Termin-Anfragen im Detail
  Termin abschließen <Firma> — Termin als erledigt markieren
  Nachfassen zeigen    — wer ist fürs Follow-up fällig
  closer starten/stoppen/status — Live-Coaching im Call
  /hilfe               — diese Nachricht
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


def _agent_status_text(runner: "AgentRunner") -> str:
    """Kompakter Agent-Überblick: Trichter + offene Tore + Antworten."""
    try:
        bericht = runner.funnel_bericht()
        laeufe  = runner.laeufe()
        am_tor  = [l for l in laeufe if l.get("status") == "wartet_auf_mensch"]
        ant     = runner.antworten()
        termine = [a for a in ant if a.get("terminwunsch")]

        zeilen = [bericht]
        if am_tor:
            zeilen.append(
                f"\n⚠️  {len(am_tor)} Kampagne(n) warten auf deine Freigabe — "
                "schreib 'freigeben' um die Mails rauszuschicken."
            )
        if termine:
            zeilen.append(
                f"\n🎯 {len(termine)} Termin-Signal(e) in den Antworten — "
                "schreib 'Antworten zeigen' für Details."
            )
        return "\n".join(zeilen)
    except Exception:
        return "📊 Kein Überblick verfügbar (Agent noch nicht gestartet)."


def _verarbeite_update(
    upd: dict, tg: TelegramAPI, cfg, mgr: DialogManager,
    agent_runner: "AgentRunner",
    closer: "CloserAdapter",
) -> None:
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
        # Dialog-Zustand + Agent-Überblick (Trichter + offene Tore + Antworten)
        dialog_status = mgr.status_text(chat_id)
        agent_status  = _agent_status_text(agent_runner)
        tg.try_send(chat_id, dialog_status + "\n\n" + agent_status)
        return

    # Natürliche Statusabfragen
    if any(w in low for w in ("wo stehen", "kampagne", "trichter", "wie viele", "überblick")):
        tg.try_send(chat_id, _agent_status_text(agent_runner))
        return

    # Termin abschließen — MUSS vor den allgemeinen Termin-/Antwort-Handlern stehen
    if any(w in low for w in ("termin abschließen", "termin abschliessen",
                               "abschließen", "abschliessen", "termin erledigt")):
        rest = low
        for w in ("termin abschließen", "termin abschliessen", "termin erledigt",
                  "abschließen", "abschliessen", "termin"):
            rest = rest.replace(w, "")
        erg = agent_runner.termin_abschliessen(rest.strip())
        tg.try_send(chat_id, erg.get("meldung", "Erledigt."))
        return

    # Postfach aktiv abrufen (E) — read-only, kein Versand
    if any(w in low for w in ("antworten abrufen", "postfach prüfen", "postfach pruefen",
                               "post abrufen", "mails abrufen", "neue antworten")):
        tg.try_send(chat_id, "📥 Ich prüfe das Postfach…")
        erg = agent_runner.antworten_abrufen()
        if erg.get("ok"):
            tg.try_send(chat_id, f"✅ {erg.get('meldung','Abruf fertig.')}\n\n{agent_runner.antworten_bericht()}")
        else:
            tg.try_send(chat_id, f"⚠️ {erg.get('meldung','Abruf nicht möglich.')}")
        return

    # Volle Detail-Ansicht aller Antworten (auf welche Mail + Antworttext)
    if any(w in low for w in ("mail zeigen", "mails zeigen", "antwort details",
                               "ganze antwort", "volle antwort", "alle antworten zeigen",
                               "details zeigen")):
        tg.try_send(chat_id, antwort_detail_bericht(agent_runner.antworten()))
        return

    # Termin-Details aufbereiten
    if any(w in low for w in ("termin", "aufbereiten", "terminanfrage")):
        tg.try_send(chat_id, termin_detail_bericht(agent_runner.antworten()))
        return

    # Antworten-Überblick (Zusammenfassung)
    if any(w in low for w in ("antworten zeigen", "antworten", "antwort", "replies")):
        tg.try_send(chat_id, agent_runner.antworten_bericht())
        return

    if any(w in low for w in ("nachfassen zeigen", "wer soll nachgefasst", "fällig")):
        faellig = agent_runner.nachfass_faellig()
        if faellig:
            zeilen = [f"⏰ {len(faellig)} Lead(s) fällig fürs Nachfassen:"]
            for f in faellig[:10]:
                zeilen.append(f"   • {f['firma']} (seit {f['faellig_seit'][:10]})")
            tg.try_send(chat_id, "\n".join(zeilen))
        else:
            tg.try_send(chat_id, "Aktuell niemand fällig fürs Nachfassen.")
        return

    # --- Closer-Befehle (eigenständig, nicht im B2B-Fluss) ---
    if any(w in low for w in ("closer starten", "closer start", "call starten",
                               "coaching starten", "/closer starten")):
        erg = closer.starten()
        if erg["ok"]:
            tg.try_send(chat_id,
                "🎤 Closer gestartet — Live-Coaching läuft.\n\n"
                "Ich höre Verkäufer + Kunde ab und gebe Echtzeit-Tipps.\n"
                "Schreib 'closer stoppen' wenn der Call fertig ist.")
        else:
            tg.try_send(chat_id, f"⚠️ Closer konnte nicht starten: {erg['meldung']}")
        return

    if any(w in low for w in ("closer stoppen", "closer stop", "call stoppen",
                               "coaching stoppen", "/closer stoppen")):
        erg = closer.stoppen()
        if erg["ok"]:
            tg.try_send(chat_id, "✅ Closer gestoppt. Guter Call!")
        else:
            tg.try_send(chat_id, f"ℹ️ {erg['meldung']}")
        return

    if any(w in low for w in ("closer status", "closer", "/closer")):
        st = closer.status()
        if st.get("laeuft"):
            tg.try_send(chat_id,
                "🎤 Closer läuft gerade — Live-Coaching aktiv.\n"
                "Schreib 'closer stoppen' wenn der Call fertig ist.")
        elif not st.get("closer_verfuegbar"):
            tg.try_send(chat_id,
                "⚠️ Closer nicht installiert. "
                "Stelle sicher dass ClouseAgent im richtigen Ordner liegt.")
        else:
            tg.try_send(chat_id,
                "🎤 Closer ist bereit — schreib 'closer starten' wenn du einen Call anfängst.")
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

    print("[boot] Rebellsystem Sales Operator startet…")

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

    # Watcher: prüft alle 5 Min ob etwas gemeldet werden muss (Termin, Tor, Nachfassen)
    # auto_abruf=True (E): ruft das Postfach selbst ab (read-only, kein Versand) —
    # so erkennt der Bot neue Antworten vollautomatisch.
    watcher = Watcher(
        runner=agent_runner,
        owner_chat_id=cfg.owner_chat_id,
        send_fn=lambda cid, txt: tg.try_send(cid, txt),
        intervall_sek=300,
        auto_abruf=True,
    )
    watcher.starten()
    print("[bot] Watcher gestartet (Intervall: 5 Min, Auto-Abruf an) — meldet Tore + Signale.")

    # Closer: eigenständig, NICHT im B2B-Fluss. Nur für Live-Calls nach Termin-Signal.
    closer_dir = (_PRODUCT_ROOT / "ClouseAgent").resolve()
    closer = CloserAdapter(closer_dir)
    if closer_dir.exists():
        print(f"[bot] Closer verfügbar: {closer_dir}")
    else:
        print(f"[bot] Closer nicht gefunden ({closer_dir}) — Befehle melden das.")

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
                    _verarbeite_update(upd, tg, cfg, mgr, agent_runner, closer)
                except Exception as exc:
                    print(f"[bot] Update-Fehler (ignoriert): {exc}")

    except KeyboardInterrupt:
        print("\n[bot] Gestoppt.")
    finally:
        _lock_freigeben()


if __name__ == "__main__":
    main()
