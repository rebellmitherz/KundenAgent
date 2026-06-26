"""Anruf-Briefing je Lead.

Bündelt drei Bausteine für den Vertriebsmitarbeiter vor dem Anruf:
  1. Firmen-Kurzprofil  — deterministisch + optionaler LLM-Feinschliff
  2. Gesprächsöffner    — bereits berechneter ``aufhaenger`` (keine Doppelarbeit)
  3. Einwand-Vorbereitung — 2 signal-passende Einwände + Antworten (0 API-Kosten)

b2bbot bleibt read-only. Diese Schicht liegt im product/-Layer.
"""
from __future__ import annotations

from typing import Callable, Optional

LLM = Callable[[str], str]

# ─── Einwand-Paare je Signal-Typ (deterministisch, 0 € laufend) ───────────────

_EINWAENDE: dict[str, list[dict]] = {
    "sales_hiring": [
        {
            "frage": "Wir haben das intern.",
            "antwort": "Genau deshalb passen wir zusammen: Wir ergänzen Ihr Team bis der Neue sitzt — und geben dem Neuen von Tag 1 qualifizierte Leads in die Hand.",
        },
        {
            "frage": "Kein Budget gerade.",
            "antwort": "Sie stellen gerade eine Vertriebskraft ein — das ist das Budget. Wir kosten einen Bruchteil davon und liefern sofort.",
        },
    ],
    "appointment_setter": [
        {
            "frage": "Wir machen die Terminierung selbst.",
            "antwort": "Das höre ich oft — meistens kostet es die falschen Leute zu viel Zeit. Was wäre, wenn Ihr Team morgen 3 qualifizierte Termine mehr hätte?",
        },
        {
            "frage": "Zu teuer.",
            "antwort": "Was kostet ein Vertriebler, der täglich kalt akquiriert statt zu verkaufen? Unsere Leads rechnen sich ab dem ersten Abschluss.",
        },
    ],
    "growth_expansion": [
        {
            "frage": "Wir wachsen gerade — kein guter Zeitpunkt.",
            "antwort": "Wachstumsphasen sind der beste Zeitpunkt: mehr Team bedeutet mehr Umsatzdruck. Saubere Leads jetzt, bevor der Neue sitzt.",
        },
        {
            "frage": "Wir haben genug Kunden.",
            "antwort": "Super — dann bauen wir die nächste Welle auf. Kaufsignale verfallen schnell. Wer jetzt spricht, kommt als Erster.",
        },
    ],
    "marketing_hiring": [
        {
            "frage": "Wir bauen das intern auf.",
            "antwort": "Perfekt — und bis das steht, füllen wir die Pipeline. Kein Widerspruch, wir ergänzen uns.",
        },
        {
            "frage": "Wir haben schon ein System.",
            "antwort": "Gut. Wir bringen etwas, das kein System liefert: Firmen, die JETZT kaufen wollen — verifiziert per Kaufsignal.",
        },
    ],
    "leadership_hiring": [
        {
            "frage": "Der Neue soll das aufbauen.",
            "antwort": "Genau — und der Neue wird sich freuen, wenn am ersten Tag qualifizierte Leads auf dem Tisch liegen.",
        },
        {
            "frage": "Erst mal intern klären.",
            "antwort": "Verstehe. Geben Sie mir 10 Minuten — bis die Stelle besetzt ist, können wir schon erste Ergebnisse zeigen.",
        },
    ],
    "new_location": [
        {
            "frage": "Wir sind noch in der Planung.",
            "antwort": "Desto besser — jetzt ist die Zeit, die Pipeline für den neuen Standort aufzubauen, bevor Tag 1 kommt.",
        },
        {
            "frage": "Kein Budget für den neuen Standort.",
            "antwort": "Mit dem richtigen Kunden zahlt sich der neue Standort von selbst. Wir liefern die Firmen, die jetzt dort kaufen wollen.",
        },
    ],
}

_EINWAENDE_FALLBACK = [
    {
        "frage": "Wir haben das intern.",
        "antwort": "Gut — wir ergänzen Ihr internes Team mit Leads, die wirklich kaufen wollen. Kein Widerspruch.",
    },
    {
        "frage": "Kein Budget gerade.",
        "antwort": "Was wäre, wenn ein Lead den nächsten Kunden bringt? Dann rechnet es sich sofort.",
    },
]

# ─── Signal → Warum-jetzt-Satz ────────────────────────────────────────────────

_SIGNAL_WARUM: dict[str, str] = {
    "sales_hiring": "sucht aktiv Vertrieb — Budget und Wachstumsabsicht sind nachgewiesen",
    "appointment_setter": "sucht Terminierer — der Outbound-Prozess wird gerade aufgebaut",
    "growth_expansion": "wächst aktiv — Ressourcen und Investitionsbereitschaft vorhanden",
    "marketing_hiring": "investiert in Marketing — Neukundengewinnung hat Priorität",
    "leadership_hiring": "holt Vertriebs- oder Marketingleitung — strategische Neuausrichtung",
    "new_location": "eröffnet einen neuen Standort — Expansionsphase mit frischem Kundenbedarf",
}

# ─── Firmen-Kurzprofil ────────────────────────────────────────────────────────

def _kurzprofil_deterministisch(lead: dict) -> str:
    firma = (lead.get("company_name") or "").strip()
    ort = (lead.get("city") or lead.get("region") or "").strip()
    signal = (lead.get("entdeckt_per_signal") or "").strip().lower()
    warum = _SIGNAL_WARUM.get(signal, "zeigt ein aktives Kaufsignal")
    beschreibung = (
        lead.get("description") or lead.get("description_raw") or
        lead.get("website_description") or ""
    ).strip()
    branche = lead.get("industry") or lead.get("ind_tokens") or ""
    if isinstance(branche, list):
        branche = ", ".join(str(b) for b in branche[:3])
    branche = str(branche).strip()

    zeilen: list[str] = []
    if beschreibung:
        erster_satz = beschreibung.split(".")[0].strip()
        if erster_satz and len(erster_satz) < 220:
            zeilen.append(erster_satz + ".")
    elif branche:
        zeilen.append(f"Tätig in: {branche}.")
    if ort:
        zeilen.append(f"Standort: {ort}.")
    name = firma or "Die Firma"
    zeilen.append(f"Warum jetzt: {name} {warum}.")
    return " ".join(zeilen) if zeilen else f"{name} — {warum}."


def firmen_kurzprofil(lead: dict, *, llm: Optional[LLM] = None) -> str:
    """3–5 Sätze Firmen-Kurzprofil. LLM verbessert, deterministischer Fallback immer."""
    basis = _kurzprofil_deterministisch(lead)
    if not llm:
        return basis
    firma = (lead.get("company_name") or "Unbekannte Firma").strip()
    signal = (lead.get("entdeckt_per_signal") or "").strip().lower()
    warum = _SIGNAL_WARUM.get(signal, "zeigt ein aktives Kaufsignal")
    prompt = (
        f"Schreib ein kompaktes Firmen-Kurzprofil (3 Sätze, Deutsch, sachlich) "
        f"für einen Vertriebsmitarbeiter, der {firma} gleich anruft. "
        f"Basis: {basis} "
        f"Kaufsignal: {firma} {warum}. "
        f"Stil: knapp, faktenbasiert, keine Floskeln, kein 'ich' oder 'wir'. "
        f"Nur die 3 Sätze, kein Titel, keine Aufzählung."
    )
    try:
        result = llm(prompt)
        result = (result or "").strip()
        return result if len(result) > 5 else basis
    except Exception:
        return basis


# ─── Öffentliche API ──────────────────────────────────────────────────────────

def einwaende_fuer_signal(signal_typ: str) -> list[dict]:
    """2 signal-passende Einwände + Antworten. Deterministisch, 0 € laufend."""
    key = (signal_typ or "").strip().lower()
    return list(_EINWAENDE.get(key, _EINWAENDE_FALLBACK))


def briefing_erstellen(lead: dict, *, llm: Optional[LLM] = None) -> dict:
    """Bündelt Kurzprofil, Opener und Einwände für einen Lead.

    Rückgabe: {kurzprofil: str, opener: str, einwaende: [{frage, antwort}, …]}
    ``opener`` liest ``lead["aufhaenger"]`` — wird von ``_signal_leads_personalisieren``
    bereits befüllt, keine Doppelarbeit.
    """
    signal = (lead.get("entdeckt_per_signal") or "").strip().lower()
    return {
        "kurzprofil": firmen_kurzprofil(lead, llm=llm),
        "opener": (lead.get("aufhaenger") or "").strip(),
        "einwaende": einwaende_fuer_signal(signal),
    }


def anreichern(leads: list[dict], *, llm: Optional[LLM] = None) -> None:
    """Hängt ``briefing`` an jeden Lead. Ein Fehler darf nichts kippen."""
    for lead in leads:
        try:
            lead["briefing"] = briefing_erstellen(lead, llm=llm)
        except Exception:
            lead.setdefault("briefing", {"kurzprofil": "", "opener": "", "einwaende": []})
