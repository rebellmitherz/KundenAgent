"""Notifier — entscheidet wann und was der Agent dem Besitzer meldet (Phase D).

Reine Logik: nimmt den aktuellen Stand vom Runner und produziert ggf. eine
Meldung. Kein Versand, keine Telegram-Abhängigkeit — alles testbar.

Drei Auslöser:
  1. Hartes Tor offen:    Agent wartet auf Mensch-Freigabe (wartet_auf_mensch)
  2. Termin-Signal:       appointment_ready in den Antworten → höchste Prio
  3. Nachfassen fällig:   Leads bereit fürs Follow-up

Jede Meldung wird nur einmal gesendet (Deduplizierung über Signatur-Hash).
So kriegt der Besitzer keinen Spam, wenn der Watcher alle 5 Min läuft.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Meldung:
    """Eine Push-Meldung an den Besitzer."""
    text: str
    signatur: str          # zum Deduplizieren (nicht nochmal senden)
    prioritaet: int = 1    # 1=hoch (Termin), 2=mittel (Tor), 3=niedrig (Info)


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def meldungen_ermitteln(
    laeufe: list[dict],
    antworten: list[dict],
    nachfass_faellig: list[dict],
    gesendete_signaturen: set[str],
) -> list[Meldung]:
    """Ermittelt alle neuen Meldungen die noch nicht gesendet wurden.

    laeufe:              runner.laeufe() — alle Kampagnen-Läufe
    antworten:           runner.antworten() — eingehende Antworten
    nachfass_faellig:    runner.nachfass_faellig() — wer nachfassen fällig
    gesendete_signaturen: bereits abgeschickte Signaturen (kein Spam)
    """
    meldungen: list[Meldung] = []

    # 1. Termin-Signale (höchste Priorität) — erledigte ausgeblendet
    termine = [a for a in antworten if a.get("terminwunsch") and not a.get("erledigt")]
    if termine:
        firmen = ", ".join(a.get("firma", "?") for a in termine[:3])
        mehr = f" und {len(termine)-3} weitere" if len(termine) > 3 else ""
        text = (
            f"🎯 Termin-Signal{'e' if len(termine)>1 else ''}!\n\n"
            f"{firmen}{mehr} {'haben' if len(termine)>1 else 'hat'} geantwortet "
            f"und {'wollen' if len(termine)>1 else 'will'} einen Termin.\n\n"
            f"👉 Schreib 'Antworten zeigen' für Details.\n"
            f"🎤 Wenn du den Call anfängst: schreib 'closer starten' — "
            f"ich coache dich live."
        )
        sig = _hash(f"termin:{'|'.join(a.get('entry_key','') for a in termine)}")
        if sig not in gesendete_signaturen:
            meldungen.append(Meldung(text=text, signatur=sig, prioritaet=1))

    # 2. Harte Tore offen (wartet auf Freigabe)
    am_tor = [l for l in laeufe if l.get("status") == "wartet_auf_mensch"]
    for lauf in am_tor:
        auftrag = lauf.get("auftrag", {})
        funnel  = lauf.get("funnel", {})
        sendbar = funnel.get("sendbar", 0)
        ziel    = funnel.get("ziel", 0)
        zg      = auftrag.get("zielgruppe", "?")
        reg     = auftrag.get("region", "?")
        text = (
            f"✅ Kampagne bereit!\n\n"
            f"🎯 {zg} · {reg}\n"
            f"📊 {sendbar}/{ziel} saubere Leads bereit.\n\n"
            f"👉 Schreib mir 'freigeben' oder öffne die Mini-UI zum Versenden."
        )
        sig = _hash(f"tor:{lauf.get('auftrags_id','')}")
        if sig not in gesendete_signaturen:
            meldungen.append(Meldung(text=text, signatur=sig, prioritaet=2))

    # 3. Nachfassen fällig
    if nachfass_faellig:
        n = len(nachfass_faellig)
        firmen = ", ".join(f.get("firma","?") for f in nachfass_faellig[:3])
        mehr = f" und {n-3} weitere" if n > 3 else ""
        text = (
            f"⏰ Nachfassen fällig!\n\n"
            f"{n} Lead{'s' if n>1 else ''}: {firmen}{mehr}.\n\n"
            f"👉 Schreib mir 'nachfassen zeigen' für die Vorschau."
        )
        # Signatur basiert auf entry_keys → ändert sich wenn neue dazukommen
        sig = _hash(f"nf:{'|'.join(f.get('entry_key','') for f in nachfass_faellig)}")
        if sig not in gesendete_signaturen:
            meldungen.append(Meldung(text=text, signatur=sig, prioritaet=3))

    # Nach Priorität sortieren (niedrigster Wert = wichtigster)
    meldungen.sort(key=lambda m: m.prioritaet)
    return meldungen
