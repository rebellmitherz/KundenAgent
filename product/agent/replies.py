"""Antworten-Bericht — macht eingehende Antworten kundenfähig (Phase B.2).

Reine Formatierung: nimmt die normalisierten Antwort-Daten (aus
bridge.antworten_lesen) und erzeugt eine ruhige, vertriebsnahe Meldung.
Hebt Terminwünsche hervor — das ist das wertvollste Signal.

Kein Versand, keine Engine-Aufrufe. Nur Text.
"""
from __future__ import annotations


def _ist_positiv(antwort: dict) -> bool:
    klasse = (antwort.get("klasse") or "").lower()
    sentiment = (antwort.get("sentiment") or "").lower()
    if antwort.get("terminwunsch"):
        return True
    if any(w in klasse for w in ("interest", "positiv", "interessiert", "meeting", "termin")):
        return True
    if sentiment in ("positiv", "positive"):
        return True
    return False


def termine(antworten: list[dict]) -> list[dict]:
    """Antworten mit Terminwunsch — das harte Signal für Phase D."""
    return [a for a in antworten if a.get("terminwunsch")]


def antworten_bericht(antworten: list[dict]) -> str:
    """Erzeugt die kundenfähige Zusammenfassung aller Antworten."""
    if not antworten:
        return "📭 Noch keine Antworten eingegangen. Ich behalte den Posteingang im Blick."

    gesamt = len(antworten)
    mit_termin = termine(antworten)
    positiv = [a for a in antworten if _ist_positiv(a) and not a.get("terminwunsch")]

    zeilen: list[str] = []
    if mit_termin:
        zeilen.append(
            f"🔔 {len(mit_termin)} Termin-Signal{'e' if len(mit_termin) != 1 else ''} "
            f"unter {gesamt} Antwort{'en' if gesamt != 1 else ''}!"
        )
    else:
        zeilen.append(
            f"📬 {gesamt} neue Antwort{'en' if gesamt != 1 else ''} eingegangen."
        )

    # Terminwünsche zuerst, ausführlich
    for a in mit_termin:
        grund = a.get("termin_grund") or "möchte einen Termin"
        zeilen.append(f"   🎯 {a.get('firma', 'Unbekannt')}: {grund}")

    # Sonstige positive Signale knapp
    for a in positiv[:5]:
        klasse = a.get("klasse") or a.get("kategorie") or "positiv"
        zeilen.append(f"   👍 {a.get('firma', 'Unbekannt')}: {klasse}")

    rest = gesamt - len(mit_termin) - len(positiv[:5])
    if rest > 0:
        zeilen.append(f"   … und {rest} weitere Antwort{'en' if rest != 1 else ''}.")

    if mit_termin:
        zeilen.append(
            "\n👉 Sag mir, wenn ich die Termin-Anfragen für dich aufbereiten soll."
        )
    return "\n".join(zeilen)
