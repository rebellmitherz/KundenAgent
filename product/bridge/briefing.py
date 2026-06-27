"""Anruf-Briefing je Lead.

Bündelt drei Bausteine für den Vertriebsmitarbeiter vor dem Anruf:
  1. Firmen-Kurzprofil  — deterministisch + optionaler LLM-Feinschliff
  2. Gesprächsöffner    — bereits berechneter ``aufhaenger`` (keine Doppelarbeit)
  3. Einwand-Vorbereitung — lead-spezifische Einwände nach Kategorie (0 API-Kosten)

b2bbot bleibt read-only. Diese Schicht liegt im product/-Layer.
"""
from __future__ import annotations

from typing import Callable, Optional

LLM = Callable[[str], str]

# ─── Lead-spezifische Einwandbehandlung (deterministisch, 0 € laufend) ────────
# Statt fixer 2 Einwände je Signal: ein Katalog nach 10 Einwand-Kategorien, aus dem
# pro Lead die wahrscheinlichsten ausgewählt und mit Lead-Feldern interpoliert werden
# (Firma, Branche, konkretes Kaufsignal, Angebot). So bekommt jeder Lead einen anderen,
# passenden Satz — kein Template-Spam. Ton: abholend, nie aggressiv, führt zum kleinen
# nächsten Schritt. (LLM-Verfeinerung später möglich — Hook in ``einwaende_fuer_lead``.)

# Kurzer Anlass je Signal: (Satz „weil Sie …", Nomen „die offene Vertriebsstelle").
_ANLASS_DEFAULT = (
    "bei Ihnen gerade ein konkretes Geschäftssignal sichtbar ist",
    "der aktuelle Anlass",
)
_ANLASS: dict[str, tuple[str, str]] = {
    "sales_hiring":       ("Sie gerade im Vertrieb einstellen", "die offene Vertriebsstelle"),
    "appointment_setter": ("Sie gerade Ihre Terminierung ausbauen", "der Ausbau Ihrer Terminierung"),
    "growth_expansion":   ("Sie gerade wachsen und Ihr Team ausbauen", "Ihre aktuelle Wachstumsphase"),
    "marketing_hiring":   ("Sie gerade in Marketing und Leadgewinnung investieren", "Ihre Marketing-Investition"),
    "leadership_hiring":  ("Sie gerade eine neue Vertriebs- oder Marketingleitung holen", "Ihre neue Führungsrolle"),
    "new_location":       ("Sie gerade einen neuen Standort aufbauen", "Ihr neuer Standort"),
}

# Einwand-Katalog nach Kategorie. antwort/ziel/naechster_schritt dürfen die Platzhalter
# {firma} {anlass_satz} {anlass_noun} {branche_phrase} {angebot_phrase} nutzen (immer gesetzt).
_EINWAND_KATALOG: dict[str, dict] = {
    "interner_aufbau": {
        "frage": "Wir bauen das gerade intern auf.",
        "antwort": "Perfekt — dann geht es nicht um Ersatz, sondern um Ergänzung. Ihr Aufbau läuft weiter, wir liefern nur Firmen, bei denen gerade ein konkreter Anlass sichtbar ist.",
        "ziel": "Von Konkurrenz auf Ergänzung umlenken.",
        "naechster_schritt": "Darf ich Ihnen ein, zwei passende Signale zeigen — ganz ohne dass Sie etwas umstellen?",
    },
    "kein_bedarf": {
        "frage": "Aktuell haben wir keinen akuten Bedarf.",
        "antwort": "Verstehe. Genau deshalb geht es nicht um Masse, sondern um wenige geprüfte Signale rund um {angebot_phrase}. Entsteht daraus kein echter Gesprächsanlass, ist es auch keins.",
        "ziel": "Druck rausnehmen, Qualität vor Menge stellen.",
        "naechster_schritt": "Soll ich mich nur melden, wenn ein Signal wirklich zu {firma} passt?",
    },
    "budget": {
        "frage": "Budget ist gerade knapp.",
        "antwort": "Nachvollziehbar. Dann fangen wir klein an — ein, zwei geprüfte Kontakte, an denen Sie sehen, ob sich der Aufwand für Sie überhaupt rechnet.",
        "ziel": "Einstieg verkleinern, Risiko senken.",
        "naechster_schritt": "Wäre ein kleiner Test mit wenigen Signalen für Sie ein fairer erster Schritt?",
    },
    "keine_zeit": {
        "frage": "Gerade keine Zeit — vielleicht später.",
        "antwort": "Klar, das Timing muss passen. Kaufsignale sind nur leider zeitkritisch — ich kann Ihnen die relevanten Firmen vormerken, bis Sie Luft haben.",
        "ziel": "Dringlichkeit ohne Druck, Tür offen halten.",
        "naechster_schritt": "Wann darf ich mich kurz wieder melden — in zwei Wochen?",
    },
    "zustaendigkeit": {
        "frage": "Dafür bin ich nicht der Richtige.",
        "antwort": "Danke für die Offenheit. Wer kümmert sich bei {firma} um neue Kundenkontakte? Dann bringe ich es direkt an die passende Stelle.",
        "ziel": "Sauber zur entscheidenden Person leiten.",
        "naechster_schritt": "Dürfen Sie mir kurz sagen, wer dafür der richtige Ansprechpartner ist?",
    },
    "vertrauen_qualitaet": {
        "frage": "Woher kommen die Daten — taugt die Qualität?",
        "antwort": "Berechtigte Frage. Anlass ist {anlass_noun} — ein öffentlich sichtbares Signal, keine gekaufte Liste. Die Quelle sehen Sie zu jedem Kontakt.",
        "ziel": "Mit Nachweis Vertrauen schaffen.",
        "naechster_schritt": "Soll ich Ihnen an einem Beispiel zeigen, wie ein Signal belegt ist?",
    },
    "rechtlich": {
        "frage": "Wie sieht das rechtlich aus?",
        "antwort": "Wichtiger Punkt. Wir arbeiten mit öffentlich belegten Geschäftssignalen und Firmendaten — Sie entscheiden, wen Sie auf welcher Grundlage ansprechen.",
        "ziel": "Bedenken ernst nehmen, Kontrolle beim Kunden lassen.",
        "naechster_schritt": "Soll ich kurz zeigen, welche Daten genau enthalten sind?",
    },
    "bestehender_dienstleister": {
        "frage": "Wir haben dafür schon einen Dienstleister.",
        "antwort": "Gut, dann steht die Basis. Wir verdrängen niemanden — wir liefern nur dort, wo gerade ein frischer Anlass sichtbar ist, als Ergänzung zum Bestehenden.",
        "ziel": "Nicht ersetzen, sondern ergänzen.",
        "naechster_schritt": "Darf ich zeigen, wo wir den bestehenden Weg sinnvoll ergänzen?",
    },
    "unterlagen": {
        "frage": "Schicken Sie mir einfach Unterlagen.",
        "antwort": "Mache ich gern — damit es nicht im Postfach untergeht, passe ich es kurz auf {firma} an. Zwei Sätze zu Ihrer Situation reichen mir.",
        "ziel": "Brush-off in ein Mini-Gespräch wandeln.",
        "naechster_schritt": "Worauf soll ich beim Zuschicken besonders eingehen?",
    },
    "skepsis_kalt": {
        "frage": "Von Kaltakquise halte ich wenig.",
        "antwort": "Verstehe ich — die meisten Anrufe kommen grundlos. Hier ist es umgekehrt: ich melde mich, weil {anlass_satz} — ein aktueller, sichtbarer Anlass, kein Zufall.",
        "ziel": "Vom Kalt-Klischee abgrenzen.",
        "naechster_schritt": "Darf ich Ihnen das eine konkrete Signal nennen, das mich auf Sie gebracht hat?",
    },
}

# Pro Signal: [wahrscheinlichster Einwand (Top), … Pool für „Weitere"]. Aus dem Pool
# werden je Lead rotierend einige gewählt (variiert pro Firma) — der Top bleibt stabil.
_SIGNAL_EINWAND_PLAN: dict[str, list[str]] = {
    "sales_hiring":       ["interner_aufbau", "bestehender_dienstleister", "kein_bedarf", "skepsis_kalt", "zustaendigkeit", "unterlagen"],
    "appointment_setter": ["bestehender_dienstleister", "interner_aufbau", "budget", "vertrauen_qualitaet", "keine_zeit", "skepsis_kalt"],
    "growth_expansion":   ["keine_zeit", "kein_bedarf", "budget", "interner_aufbau", "unterlagen", "skepsis_kalt"],
    "marketing_hiring":   ["bestehender_dienstleister", "zustaendigkeit", "vertrauen_qualitaet", "kein_bedarf", "keine_zeit", "unterlagen"],
    "leadership_hiring":  ["zustaendigkeit", "keine_zeit", "interner_aufbau", "kein_bedarf", "unterlagen", "skepsis_kalt"],
    "new_location":       ["kein_bedarf", "keine_zeit", "budget", "vertrauen_qualitaet", "skepsis_kalt", "unterlagen"],
}
_FALLBACK_PLAN = ["kein_bedarf", "interner_aufbau", "budget", "keine_zeit", "skepsis_kalt", "vertrauen_qualitaet"]

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


# ─── Einwand-Generierung (lead-spezifisch) ────────────────────────────────────

def _einwand_ctx(lead: dict, angebot: str) -> dict:
    """Platzhalter-Werte aus dem Lead-Kontext — alle immer gesetzt (keine Leerstellen)."""
    firma = (lead.get("company_name") or "").strip() or "das Unternehmen"
    signal = (lead.get("entdeckt_per_signal") or "").strip().lower()
    anlass_satz, anlass_noun = _ANLASS.get(signal, _ANLASS_DEFAULT)
    branche = lead.get("industry") or lead.get("ind_tokens") or ""
    if isinstance(branche, list):
        branche = ", ".join(str(b) for b in branche[:2])
    branche = str(branche).strip()
    branche_phrase = f"gerade in {branche}" if branche else "gerade bei vergleichbaren Firmen"
    ang = (angebot or "").strip()
    angebot_phrase = ang if ang and ang not in ("—", "-") else "Ihr Kerngeschäft"
    return {
        "firma": firma,
        "anlass_satz": anlass_satz,
        "anlass_noun": anlass_noun,
        "branche_phrase": branche_phrase,
        "angebot_phrase": angebot_phrase,
    }


def _fmt_einwand(kategorie: str, ctx: dict) -> dict:
    """Einen Katalog-Einwand mit dem Lead-Kontext füllen."""
    t = _EINWAND_KATALOG.get(kategorie) or _EINWAND_KATALOG["kein_bedarf"]
    def _f(s: str) -> str:
        try:
            return s.format(**ctx)
        except Exception:
            return s
    return {
        "frage": t["frage"],
        "antwort": _f(t["antwort"]),
        "ziel": _f(t["ziel"]),
        "naechster_schritt": _f(t["naechster_schritt"]),
    }


def einwaende_fuer_lead(lead: dict, *, angebot: str = "", anzahl: int = 5) -> list[dict]:
    """Lead-spezifische Einwände: wahrscheinlichster zuerst, danach pro Firma variierte
    „Weitere". Jeder Einwand: ``{frage, antwort, ziel, naechster_schritt}``.

    Deterministisch (0 €): Auswahl + Reihenfolge ergeben sich aus Signal und Firmenname,
    die Texte werden mit Firma/Branche/Anlass/Angebot interpoliert. Kein Template-Spam —
    zwei Firmen mit gleichem Signal bekommen unterschiedliche „Weitere"-Sets.
    """
    signal = (lead.get("entdeckt_per_signal") or "").strip().lower()
    plan = _SIGNAL_EINWAND_PLAN.get(signal, _FALLBACK_PLAN)
    top, pool = plan[0], list(plan[1:])
    # Pro Firma rotieren, damit die „Weiteren" variieren (Top bleibt = wahrscheinlichster).
    firma = (lead.get("company_name") or "").strip()
    if pool:
        start = (sum(ord(c) for c in firma) % len(pool)) if firma else 0
        pool = pool[start:] + pool[:start]
    chosen = [top] + pool[: max(int(anzahl) - 1, 0)]
    ctx = _einwand_ctx(lead, angebot)
    return [_fmt_einwand(k, ctx) for k in chosen]


def einwaende_fuer_signal(signal_typ: str) -> list[dict]:
    """Rückwärts-kompatibel: Einwände für ein Signal ohne weiteren Lead-Kontext."""
    return einwaende_fuer_lead({"entdeckt_per_signal": signal_typ})


# ─── Öffentliche API ──────────────────────────────────────────────────────────

def briefing_erstellen(lead: dict, *, angebot: str = "", llm: Optional[LLM] = None) -> dict:
    """Bündelt Kurzprofil, Opener und lead-spezifische Einwände für einen Lead.

    Rückgabe: ``{kurzprofil, opener, einwaende: [{frage, antwort, ziel, naechster_schritt}, …]}``
    ``opener`` liest ``lead["aufhaenger"]`` — wird von ``_signal_leads_personalisieren``
    bereits befüllt, keine Doppelarbeit. ``angebot`` fließt in die Einwand-Antworten ein.
    """
    return {
        "kurzprofil": firmen_kurzprofil(lead, llm=llm),
        "opener": (lead.get("aufhaenger") or "").strip(),
        "einwaende": einwaende_fuer_lead(lead, angebot=angebot),
    }


def anreichern(leads: list[dict], *, angebot: str = "", llm: Optional[LLM] = None) -> None:
    """Hängt ``briefing`` an jeden Lead. Ein Fehler darf nichts kippen."""
    for lead in leads:
        try:
            lead["briefing"] = briefing_erstellen(lead, angebot=angebot, llm=llm)
        except Exception:
            lead.setdefault("briefing", {"kurzprofil": "", "opener": "", "einwaende": []})
