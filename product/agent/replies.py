"""Antworten-Bericht — macht eingehende Antworten kundenfähig (Phase B.2).

Reine Formatierung: nimmt die normalisierten Antwort-Daten (aus
bridge.antworten_lesen) und erzeugt eine ruhige, vertriebsnahe Meldung.
Hebt Terminwünsche hervor — das ist das wertvollste Signal.

Kein Versand, keine Engine-Aufrufe. Nur Text.
"""
from __future__ import annotations

from product.agent.signalqualitaet import triage


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


def termine(antworten: list[dict], llm_fn=None) -> list[dict]:
    """Offene, **bestätigte** Termin-Signale — das harte Signal für Phase D.

    Seit F1 läuft jedes Termin-Signal durch die Signalqualitäts-Triage: nur
    Antworten, die der Prüfung standhalten (keine Auto-Antwort, keine klare
    Absage), gelten als bestätigter Termin. Erledigte werden ausgeblendet.
    Widersprüchliche Signale landen in pruef_termine() statt hier."""
    return triage(antworten, llm_fn=llm_fn)["bestaetigt"]


def pruef_termine(antworten: list[dict], llm_fn=None) -> list[dict]:
    """Offene Termin-Signale, die der Prüfung NICHT eindeutig standhalten.

    Werden dem Menschen leise zur Prüfung vorgelegt — nie als sicherer Termin
    verkauft (Engine-Fehlalarme, Abwesenheitsnotizen)."""
    return triage(antworten, llm_fn=llm_fn)["pruefen"]


def _datum_kurz(wert: str) -> str:
    """'2026-04-27T23:49:09' → '27.04.2026'. Leerwert bleibt leer."""
    wert = (wert or "").strip()
    if len(wert) >= 10 and wert[4] == "-" and wert[7] == "-":
        return f"{wert[8:10]}.{wert[5:7]}.{wert[0:4]}"
    return wert


def _antwort_block(i: int, a: dict) -> list[str]:
    """Ein detaillierter Antwort-Block: auf welche Mail, aus welchem Postfach,
    der Antworttext selbst. Gemeinsame Formatierung für Termin- und Voll-Ansicht."""
    firma = a.get("firma") or "Unbekannt"
    von = a.get("von") or ""
    betreff = a.get("betreff") or ""
    auszug = (a.get("auszug") or "").strip()
    grund = a.get("termin_grund") or ""
    postfach = a.get("postfach") or ""
    gesendet = _datum_kurz(a.get("gesendet_am") or "")

    zeilen = [f"── {i}. {firma} ──"]
    if von:
        zeilen.append(f"   Von:      {von}")
    if betreff:
        zeilen.append(f"   Betreff:  {betreff}")
    if gesendet:
        zeilen.append(f"   Auf Mail vom: {gesendet}" + (f" ({postfach})" if postfach else ""))
    elif postfach:
        zeilen.append(f"   Postfach: {postfach}")
    if a.get("terminwunsch") and grund:
        zeilen.append(f"   Signal:   🎯 {grund}")
    if auszug:
        zeilen.append(f"   Antwort:  {auszug[:400]}")
    return zeilen


def termin_detail_bericht(antworten: list[dict]) -> str:
    """Detaillierte Aufbereitung der Termin-Signale inkl. E-Mail-Auszug."""
    mit_termin = termine(antworten)
    if not mit_termin:
        return "📭 Aktuell keine Termin-Signale vorhanden."

    zeilen = [f"🎯 {len(mit_termin)} Termin-Anfrage(n) — hier die Details:\n"]
    for i, a in enumerate(mit_termin, 1):
        zeilen.extend(_antwort_block(i, a))
        zeilen.append("")

    zeilen.append("👉 Wenn du den Call anfängst: schreib 'closer starten'.")
    zeilen.append("✅ Erledigt? Schreib 'Termin abschließen <Firma>'.")
    return "\n".join(zeilen)


def antwort_detail_bericht(antworten: list[dict]) -> str:
    """Volle Detailansicht ALLER Antworten (auf welche Mail + Antworttext).

    Auto-Antworten (Out-of-Office) ans Ende, echte Antworten zuerst."""
    if not antworten:
        return "📭 Noch keine Antworten eingegangen. Ich behalte den Posteingang im Blick."

    echte = [a for a in antworten if not a.get("auto_antwort")]
    autos = [a for a in antworten if a.get("auto_antwort")]
    geordnet = echte + autos

    zeilen = [f"📬 {len(antworten)} Antwort(en) — Details:\n"]
    for i, a in enumerate(geordnet, 1):
        block = _antwort_block(i, a)
        if a.get("auto_antwort"):
            block[0] += "  (automatische Antwort)"
        zeilen.extend(block)
        zeilen.append("")
    return "\n".join(zeilen)


def antworten_bericht(antworten: list[dict]) -> str:
    """Erzeugt die kundenfähige Zusammenfassung aller Antworten."""
    if not antworten:
        return "📭 Noch keine Antworten eingegangen. Ich behalte den Posteingang im Blick."

    gesamt = len(antworten)
    sortiert = triage(antworten)
    mit_termin = sortiert["bestaetigt"]
    zu_pruefen = sortiert["pruefen"]
    positiv = [
        a for a in antworten
        if _ist_positiv(a) and not a.get("terminwunsch")
    ]

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

    # Bestätigte Terminwünsche zuerst, ausführlich
    for a in mit_termin:
        grund = a.get("termin_grund") or "möchte einen Termin"
        zeilen.append(f"   🎯 {a.get('firma', 'Unbekannt')}: {grund}")

    # Ehrlich: widersprüchliche Signale leise zur Prüfung, NICHT als Termin
    for a in zu_pruefen:
        zeilen.append(
            f"   🔎 {a.get('firma', 'Unbekannt')}: Antwort prüfen "
            "(kein eindeutiger Terminwunsch)."
        )

    # Sonstige positive Signale knapp
    for a in positiv[:5]:
        klasse = a.get("klasse") or a.get("kategorie") or "positiv"
        zeilen.append(f"   👍 {a.get('firma', 'Unbekannt')}: {klasse}")

    rest = gesamt - len(mit_termin) - len(zu_pruefen) - len(positiv[:5])
    if rest > 0:
        zeilen.append(f"   … und {rest} weitere Antwort{'en' if rest != 1 else ''}.")

    if mit_termin:
        zeilen.append(
            "\n👉 Sag mir, wenn ich die Termin-Anfragen für dich aufbereiten soll."
        )
    return "\n".join(zeilen)
