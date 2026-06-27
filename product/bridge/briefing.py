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
            "ziel": "Ergänzung statt Konkurrenz signalisieren — Budget-Freigabe beschleunigen.",
            "naechster_schritt": "Darf ich kurz zeigen, wie das in der Praxis bei ähnlichen Teams aussieht? 10 Minuten reichen.",
            "nicht_sagen": "Ihr internes Team reicht nicht aus / Das kann Ihr Team nicht — löst sofortige Defensivreaktion aus.",
        },
        {
            "frage": "Kein Budget gerade.",
            "antwort": "Sie stellen gerade eine Vertriebskraft ein — das ist das Budget. Wir kosten einen Bruchteil davon und liefern sofort.",
            "ziel": "Budget-Einwand als Denkfehler enttarnen — ROI ins Verhältnis zum Sales-Gehalt setzen.",
            "naechster_schritt": "Darf ich Ihnen ein konkretes Rechenbeispiel schicken — was ein Abschluss bei Ihnen im Schnitt wert ist?",
            "nicht_sagen": "Wir sind sehr günstig / konkrete Preise nennen — eröffnet Preisgespräch zu früh.",
        },
    ],
    "appointment_setter": [
        {
            "frage": "Wir machen die Terminierung selbst.",
            "antwort": "Das höre ich oft — meistens kostet es die falschen Leute zu viel Zeit. Was wäre, wenn Ihr Team morgen 3 qualifizierte Termine mehr hätte?",
            "ziel": "Aufwand und Opportunitätskosten bewusst machen — Neugier auf Ergebnisvergleich wecken.",
            "naechster_schritt": "Was wäre, wenn wir das einfach 2 Wochen parallel laufen lassen? Zahlen sprechen für sich.",
            "nicht_sagen": "Ihr Prozess ist ineffizient — erzeugt sofort Gegendruck und Defensivhaltung.",
        },
        {
            "frage": "Zu teuer.",
            "antwort": "Was kostet ein Vertriebler, der täglich kalt akquiriert statt zu verkaufen? Unsere Leads rechnen sich ab dem ersten Abschluss.",
            "ziel": "Kosten in Relation zu Vertriebskosten setzen — Preis als Investition, nicht als Ausgabe frames.",
            "naechster_schritt": "Darf ich kurz fragen: Was kostet Sie ein qualifizierter Termin aktuell, alles reingerechnet?",
            "nicht_sagen": "Sofort Rabatt anbieten oder defensiv auf den Preis eingehen — entwertet das Produkt.",
        },
    ],
    "growth_expansion": [
        {
            "frage": "Wir wachsen gerade — kein guter Zeitpunkt.",
            "antwort": "Wachstumsphasen sind der beste Zeitpunkt: mehr Team bedeutet mehr Umsatzdruck. Saubere Leads jetzt, bevor der Neue sitzt.",
            "ziel": "Wachstumsphase als Kaufargument umdrehen — jetzt handeln statt später nacharbeiten.",
            "naechster_schritt": "Genau deshalb: darf ich kurz zeigen, welche Leads gerade für Ihre Wachstumsphase passen?",
            "nicht_sagen": "Das ist eigentlich der perfekte Zeitpunkt — klingt besserwisserisch, lieber indirekt führen.",
        },
        {
            "frage": "Wir haben genug Kunden.",
            "antwort": "Super — dann bauen wir die nächste Welle auf. Kaufsignale verfallen schnell. Wer jetzt spricht, kommt als Erster.",
            "ziel": "Pipeline-Denken wecken — nächste Wachstumswelle rechtzeitig vorbereiten.",
            "naechster_schritt": "Wann planen Sie die nächste Wachstumsphase? Dann wäre jetzt genau der richtige Moment.",
            "nicht_sagen": "Das kann sich schnell ändern — klingt bedrohlich, schafft Widerstand.",
        },
    ],
    "marketing_hiring": [
        {
            "frage": "Wir bauen das intern auf.",
            "antwort": "Perfekt — und bis das steht, füllen wir die Pipeline. Kein Widerspruch, wir ergänzen uns.",
            "ziel": "Übergangs-Lösung anbieten bis Go-live — keine Konkurrenz zum internen Aufbau.",
            "naechster_schritt": "Wie lange schätzen Sie, bis das intern steht? Bis dahin halten wir die Pipeline am Laufen.",
            "nicht_sagen": "Interne Lösungen dauern immer länger — provokativ, erzeugt sofort Abwehrhaltung.",
        },
        {
            "frage": "Wir haben schon ein System.",
            "antwort": "Gut. Wir bringen etwas, das kein System liefert: Firmen, die JETZT kaufen wollen — verifiziert per Kaufsignal.",
            "ziel": "Kaufsignal-Qualität als Alleinstellungsmerkmal herausstellen — kein System-Vergleich, sondern Ergänzung.",
            "naechster_schritt": "Darf ich fragen: Wie verifiziert Ihr System aktuell, ob eine Firma JETZT kaufen will?",
            "nicht_sagen": "Unser System ist besser — System-Vergleich ist eine Falle, die Sie nicht gewinnen.",
        },
    ],
    "leadership_hiring": [
        {
            "frage": "Der Neue soll das aufbauen.",
            "antwort": "Genau — und der Neue wird sich freuen, wenn am ersten Tag qualifizierte Leads auf dem Tisch liegen.",
            "ziel": "Quick-Win für neue Führungskraft positionieren — Leads als Geschenk, nicht als Konkurrenz.",
            "naechster_schritt": "Was wäre, wenn der Neue am ersten Tag schon eine fertige Pipeline vorfindet? Das macht einen Eindruck.",
            "nicht_sagen": "Der Neue braucht erst Zeit — klingt kritisch gegenüber der Entscheidung des Gesprächspartners.",
        },
        {
            "frage": "Erst mal intern klären.",
            "antwort": "Verstehe. Geben Sie mir 10 Minuten — bis die Stelle besetzt ist, können wir schon erste Ergebnisse zeigen.",
            "ziel": "Dringlichkeit aufbauen ohne Druck — Kaufsignale verfallen, Timing ist entscheidend.",
            "naechster_schritt": "Darf ich Ihnen in der Zwischenzeit 2–3 passende Leads zeigen — zur Orientierung, unverbindlich?",
            "nicht_sagen": "Wie lange dauert das intern? — klingt ungeduldig, erzeugt Druck und Widerstand.",
        },
    ],
    "new_location": [
        {
            "frage": "Wir sind noch in der Planung.",
            "antwort": "Desto besser — jetzt ist die Zeit, die Pipeline für den neuen Standort aufzubauen, bevor Tag 1 kommt.",
            "ziel": "Planungsphase als idealen Startpunkt verkaufen — Pipeline aufbauen vor Eröffnung.",
            "naechster_schritt": "Wann ist der geplante Eröffnungstermin? Dann planen wir die Lead-Pipeline rückwärts.",
            "nicht_sagen": "Dann rufen Sie an, wenn Sie soweit sind — beendet das Gespräch, Momentum geht verloren.",
        },
        {
            "frage": "Kein Budget für den neuen Standort.",
            "antwort": "Mit dem richtigen Kunden zahlt sich der neue Standort von selbst. Wir liefern die Firmen, die jetzt dort kaufen wollen.",
            "ziel": "Standort als Investment frames — erste Kunden finanzieren den Standort selbst.",
            "naechster_schritt": "Wie viele Kunden brauchen Sie, damit sich der Standort rechnet? Genau das liefern wir.",
            "nicht_sagen": "Budget ist kein Problem bei uns — ignoriert den echten Einwand, wirkt unsensibel.",
        },
    ],
}

_EINWAENDE_FALLBACK = [
    {
        "frage": "Wir haben das intern.",
        "antwort": "Gut — wir ergänzen Ihr internes Team mit Leads, die wirklich kaufen wollen. Kein Widerspruch.",
        "ziel": "Ergänzungsnutzen herausstellen — keine Konkurrenz, sondern Hebelwirkung für das bestehende Team.",
        "naechster_schritt": "Darf ich zeigen, welche Leads aktuell zu Ihrem Setup passen?",
        "nicht_sagen": "Intern reicht das nicht — erzeugt sofortige Abwehrhaltung.",
    },
    {
        "frage": "Kein Budget gerade.",
        "antwort": "Was wäre, wenn ein Lead den nächsten Kunden bringt? Dann rechnet es sich sofort.",
        "ziel": "ROI-Perspektive öffnen — ein Abschluss rechtfertigt die Investition sofort.",
        "naechster_schritt": "Darf ich kurz fragen: Was wäre ein Abschluss bei Ihnen wert? Dann rechnen wir kurz zusammen.",
        "nicht_sagen": "Sofort Preis nennen oder nachgeben — entwertet das Angebot dauerhaft.",
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
