"""Kampagnen-Trichter — leitet je Lead die Stufe ab und macht sie kundenfähig.

Reine Logik (keine Engine-, keine Datei-Aufrufe): nimmt die Rohdaten aus
bridge.kampagne_rohdaten und bestimmt für jeden Lead seine aktuelle Stufe im
Trichter — und erzeugt eine ruhige, vertriebsnahe Übersicht „wo steht wer".

Stufen (aufsteigend, jeder Lead steht auf der WEITESTEN erreichten):
  gefunden → bereit → angeschrieben → geantwortet → termin
"""
from __future__ import annotations

# Reihenfolge = Trichter von oben nach unten
STUFEN = ["gefunden", "bereit", "angeschrieben", "geantwortet", "termin"]

_LABELS = {
    "gefunden":     "🔍 gefunden",
    "bereit":       "✅ versandbereit",
    "angeschrieben": "📧 angeschrieben",
    "geantwortet":  "💬 geantwortet",
    "termin":       "🎯 Termine",
}


def stufe_von(entry: dict, antwort_keys: set, termin_keys: set) -> str:
    """Bestimmt die weiteste erreichte Stufe eines Leads."""
    ek = entry.get("entry_key", "")
    if ek and ek in termin_keys:
        return "termin"
    if ek and ek in antwort_keys:
        return "geantwortet"
    if entry.get("gesendet"):
        return "angeschrieben"
    if entry.get("bereit"):
        return "bereit"
    return "gefunden"


def funnel_aus_rohdaten(roh: dict, lead_limit: int = 50) -> dict:
    """Erzeugt aus den Bridge-Rohdaten die Trichter-Übersicht.

    Zählt ALLE Leads je Stufe; die Lead-Liste wird auf lead_limit gekürzt
    (für die Anzeige) — die Zählung bleibt vollständig.
    """
    antwort = set(roh.get("antwort_keys") or [])
    termin = set(roh.get("termin_keys") or [])
    entries = roh.get("entries") or []

    counts = {s: 0 for s in STUFEN}
    leads: list[dict] = []
    for e in entries:
        s = stufe_von(e, antwort, termin)
        counts[s] += 1
        if len(leads) < lead_limit:
            leads.append({
                "firma":           e.get("firma", ""),
                "ort":             e.get("ort", ""),
                "ansprechpartner": e.get("ansprechpartner", ""),
                "stufe":           s,
            })
    return {"gesamt": len(entries), "stufen": counts, "leads": leads}


def _delta_text(jetzt: int, vorher: int) -> str:
    diff = jetzt - vorher
    if diff > 0:
        return f"  (+{diff})"
    return ""


def funnel_bericht(funnel: dict, vorher: dict | None = None) -> str:
    """Kundenfähige Trichter-Übersicht. vorher = stufen-dict eines früheren
    Snapshots → zeigt den Zuwachs (Trend)."""
    gesamt = funnel.get("gesamt", 0)
    st = funnel.get("stufen", {})
    if gesamt == 0:
        return "📊 Noch keine Leads in dieser Kampagne. Ich lege los, sobald es welche gibt."

    zeilen = [f"📊 Kampagne — wo steht wer ({gesamt} Leads):"]
    for s in STUFEN:
        delta = _delta_text(st.get(s, 0), vorher.get(s, 0)) if vorher else ""
        zeilen.append(f"   {_LABELS[s]}: {st.get(s, 0)}{delta}")

    termine = st.get("termin", 0)
    if termine:
        zeilen.append(
            f"\n🎯 {termine} Termin{'e' if termine != 1 else ''}! "
            "Sag mir, wenn ich sie für dich aufbereiten soll."
        )
    return "\n".join(zeilen)
