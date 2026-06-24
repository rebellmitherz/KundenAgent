"""Signal-Aufhänger — verkaufspsychologischer Einstiegssatz pro Lead.

Warum diese Schicht existiert
------------------------------
Eine generische Erstmail wirkt austauschbar. Wenn die Lead-Suche aber ein
konkretes **Signal** über die Firma kennt (z. B. „stellt gerade Vertrieb ein"
oder — Phase 2 — „Website hat keinen klaren Call-to-Action"), kann die Mail mit
EINER personalisierten Beobachtung starten. Der Ansprechpartner merkt sofort:
„Der hat sich meinen Laden angeschaut, das ist kein Massenmail." Das ist der
Hebel für Antwortquote und Umsatz.

Wichtig — wann personalisiert wird
----------------------------------
NUR bei Signal-Suche. Liegt kein Signal vor, gibt diese Schicht "" zurück und
die Engine baut ihre normale (gute) Standard-Mail. Es wird NICHTS erfunden.

Hybrid-Architektur (Entscheidung Michael 2026-06-14)
----------------------------------------------------
1. Regeln (deterministisch) erkennen aus den Signaldaten den *Aufhänger-Typ*
   und ziehen die belegbaren Fakten heraus. Kein Halluzinieren möglich.
2. Ein LLM (OpenAI) formuliert daraus 1–2 natürliche Sätze auf den
   Ansprechpartner abgestimmt — verkaufspsychologisch, „Sie", ohne Floskeln.
3. Kein API-Key / LLM-Fehler → deterministischer Fallback-Satz aus den Regeln.
   Das System bleibt also IMMER funktionsfähig, der Key hebt nur die Qualität.

Diese Schicht macht KEINEN Netz-/API-Call beim bloßen Import oder im Test —
das LLM wird als Callable injiziert (Tests übergeben ein Fake).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

# Ein LLM ist eine Funktion prompt -> Satz. None = kein LLM verfügbar.
LLM = Callable[[str], str]

# Erlaubte Angebot-Typen (entsprechen den Multi-Offer-Profilen).
ANGEBOT_KUNDENAGENT = "kundenagent"
ANGEBOT_AKQUISE = "akquise"
ANGEBOT_WEBSITE = "website"
ANGEBOT_VERSICHERUNG = "versicherung"


@dataclass
class Aufhaenger:
    """Ein erkannter Aufhänger: WAS wir gesehen haben + ein sicherer Fallback-Satz."""
    typ: str                              # z. B. "hiring_sales", "growth", "website_schwaeche"
    fakten: dict = field(default_factory=dict)   # belegbare Fakten (gehen 1:1 ins LLM-Prompt)
    fallback_satz: str = ""               # deterministischer Satz ohne LLM


# ─── Schritt 1: Regeln — Signal → Aufhänger (deterministisch) ────────────────

def aufhaenger_angle(lead: dict, angebot_typ: str) -> Optional[Aufhaenger]:
    """Erkennt aus einem Lead den passenden Aufhänger. None = kein Signal."""
    angebot = (angebot_typ or "").strip().lower()

    if angebot == ANGEBOT_WEBSITE:
        return _website_angle(lead)
    if angebot == ANGEBOT_VERSICHERUNG:
        return _versicherung_angle(lead)
    if angebot in (ANGEBOT_KUNDENAGENT, ANGEBOT_AKQUISE):
        return _akquise_angle(lead)
    return None


def _akquise_angle(lead: dict) -> Optional[Aufhaenger]:
    """KundenAgent + Akquise teilen dasselbe Signal: die Firma hat Kundenbedarf.

    Quelle sind die Felder, die signal_discovery/engine_bridge pro Lead heften:
    ``entdeckt_per_signal``, ``signal_titel``, ``signal_quelle_url``.
    """
    signal = (lead.get("entdeckt_per_signal") or "").strip()
    titel = (lead.get("signal_titel") or "").strip()
    quelle = (lead.get("signal_quelle_url") or "").strip()

    if signal == "sales_hiring":
        return Aufhaenger(
            typ="hiring_sales",
            fakten={"stellentitel": titel, "quelle": quelle},
            fallback_satz=(
                "Mir ist aufgefallen, dass Sie aktuell Vertrieb verstärken – "
                "Neukundengewinnung steht bei Ihnen also ohnehin gerade oben auf der Liste."
            ),
        )
    if signal == "growth_expansion":
        return Aufhaenger(
            typ="growth",
            fakten={"hinweis": titel, "quelle": quelle},
            fallback_satz=(
                "Mir ist aufgefallen, dass Sie gerade wachsen – genau die Phase, in der "
                "planbarer Nachschub an Erstgesprächen den Unterschied macht."
            ),
        )
    # NEU (Weg-2-Tiefe): die 4 zusätzlichen Signaltypen teilen die Grund-Logik
    # (akuter Kundenbedarf), je mit eigenem Aufhänger. Ohne diese Zweige bekäme
    # ein neues Signal einen leeren Hook → generische Mail.
    _NEUE_ANGLES = {
        "appointment_setter": (
            "outbound_setup",
            "Mir ist aufgefallen, dass Sie gerade Outbound/Terminierung aufbauen – genau da "
            "macht ein Strom vorqualifizierter Ersttermine den Unterschied.",
        ),
        "marketing_hiring": (
            "marketing_invest",
            "Mir ist aufgefallen, dass Sie gerade in Marketing investieren – planbare "
            "Erstgespräche mit passenden Firmen sind die logische Ergänzung zur Reichweite.",
        ),
        "leadership_hiring": (
            "sales_leadership",
            "Mir ist aufgefallen, dass Sie gerade Vertriebs-/Marketingleitung an Bord holen – "
            "die will früh planbare Pipeline zeigen, nicht auf Zufalls-Inbound warten.",
        ),
        "new_location": (
            "new_location",
            "Mir ist aufgefallen, dass Sie gerade einen neuen Standort aufbauen – lokale "
            "Erstkunden sind dabei meist das Nadelöhr.",
        ),
    }
    if signal in _NEUE_ANGLES:
        typ, fallback = _NEUE_ANGLES[signal]
        return Aufhaenger(typ=typ, fakten={"hinweis": titel, "quelle": quelle}, fallback_satz=fallback)
    return None


def _versicherung_angle(lead: dict) -> Optional[Aufhaenger]:
    """Versicherungs-Angebot: jedes vs_*-Signal ist eine Veränderung, die eine
    Deckungslücke aufreißt. Der Makler eröffnet den Call mit genau diesem Trigger
    (nicht mit „brauchen Sie Versicherung?"). Jeder Lead bekommt so einen fertigen,
    belegbaren Aufhänger-Satz — auch ohne LLM. Quelle: ``entdeckt_per_signal``.
    """
    signal = (lead.get("entdeckt_per_signal") or "").strip().lower()
    titel = (lead.get("signal_titel") or "").strip()
    quelle = (lead.get("signal_quelle_url") or "").strip()
    angle = _VS_ANGLES.get(signal)
    if not angle:
        return None
    typ, fallback = angle
    return Aufhaenger(typ=typ, fakten={"hinweis": titel, "quelle": quelle}, fallback_satz=fallback)


# Versicherungs-Signal → (Aufhänger-Typ, deterministischer Fallback-Satz). Der
# Satz ist ein respektvoller Gesprächseinstieg, der den Trigger benennt und sanft
# auf die mögliche Deckungslücke überleitet — sachlich, keine Panikmache.
_VS_ANGLES: dict[str, tuple[str, str]] = {
    "vs_hiring": (
        "vs_hiring",
        "Mir ist aufgefallen, dass Sie gerade einstellen – da lohnt ein kurzer Blick, "
        "ob die betriebliche Altersvorsorge inklusive der 15-%-Zuschusspflicht für die "
        "neuen Mitarbeiter sauber mitgewachsen ist.",
    ),
    "vs_benefits": (
        "vs_benefits",
        "Mir ist aufgefallen, dass Sie aktiv mit Benefits werben – erfahrungsgemäß ist "
        "die bAV/bKV dabei selten optimal aufgesetzt, ein kurzer Check holt da oft mehr "
        "für Ihre Leute heraus.",
    ),
    "vs_fuhrpark": (
        "vs_fuhrpark",
        "Mir ist aufgefallen, dass bei Ihnen Fahrer bzw. Außendienst unterwegs sind – "
        "bei Fuhrparks klaffen im Schadenfall oft Lücken, gerade beim Insassen-/"
        "Gruppenunfallschutz, das lässt sich schnell prüfen.",
    ),
    "vs_standort": (
        "vs_standort",
        "Mir ist aufgefallen, dass Sie gerade einen neuen Standort aufbauen – die "
        "Versicherungen laufen in so einer Phase oft noch auf altem Stand und decken "
        "den neuen Betrieb nicht voll ab.",
    ),
    "vs_produktion": (
        "vs_produktion",
        "Mir ist aufgefallen, dass bei Ihnen Produktion bzw. Maschinen im Spiel sind – "
        "ein einziger längerer Betriebsausfall kostet dort schnell mehr als die "
        "Jahresprämie, deshalb lohnt der kurze Blick auf die Absicherung.",
    ),
    "vs_cyber": (
        "vs_cyber",
        "Mir ist aufgefallen, dass bei Ihnen IT bzw. Kundendaten eine zentrale Rolle "
        "spielen – Cyber-Absicherung wird gerade zum Pflichtthema (NIS2), ein kurzer "
        "Risiko-Check lohnt sich, bevor etwas passiert.",
    ),
}


def _website_angle(lead: dict) -> Optional[Aufhaenger]:
    """Website-Angebot (Phase 2): konkrete, gemessene Schwächen der echten Seite.

    Erwartet ``website_schwaechen`` als Liste von Kurz-Codes (z. B. ["kein_ssl",
    "langsam_mobil", "kein_cta"]). Der Detektor, der diese Liste füllt, kommt in
    Phase 3 — hier ist die Verarbeitung schon vorbereitet, damit die Mail-Kette
    dann nur noch andockt.
    """
    schwaechen = [str(s).strip() for s in (lead.get("website_schwaechen") or []) if str(s).strip()]
    if not schwaechen:
        return None
    labels = [_WEBSITE_SCHWAECHE_LABEL.get(code, code) for code in schwaechen]
    # Maximal die zwei stärksten Punkte — eine Mail soll nicht abkanzeln.
    top = labels[:2]
    if len(top) == 1:
        fallback = f"Mir ist auf Ihrer Seite aufgefallen: {top[0]} – genau so verlieren Sie Anfragen."
    else:
        fallback = (
            f"Mir ist auf Ihrer Seite aufgefallen: {top[0]} und {top[1]} – "
            "das sind die Punkte, an denen Besucher abspringen, statt anzufragen."
        )
    return Aufhaenger(
        typ="website_schwaeche",
        fakten={"schwaechen": top, "url": (lead.get("website") or "").strip()},
        fallback_satz=fallback,
    )


# Menschliche Labels für die Website-Schwäche-Codes (Phase 2/3 füllt die Codes).
_WEBSITE_SCHWAECHE_LABEL = {
    "kein_ssl": "die Seite läuft noch ohne HTTPS-Verschlüsselung",
    "langsam_mobil": "auf dem Smartphone lädt die Startseite spürbar langsam",
    "kein_cta": "ein klarer Weg zur Kontaktanfrage fehlt auf den ersten Blick",
    "kein_impressum": "ein Impressum ist nicht auffindbar",
    "veraltet": "die Inhalte wirken nicht mehr aktuell gepflegt",
    "nicht_mobil": "die Seite ist auf dem Smartphone nur schwer bedienbar",
}


# ─── Schritt 2: LLM formuliert den Satz (mit sicherem Fallback) ──────────────

def aufhaenger_text(
    lead: dict,
    angebot_typ: str,
    *,
    llm: Optional[LLM] = None,
    firma: str = "",
    branche: str = "",
    ansprechpartner: str = "",
) -> str:
    """Liefert den personalisierten Aufhänger-Satz — oder "" ohne Signal.

    Reihenfolge: Regeln finden den Aufhänger → LLM formuliert → bei fehlendem
    LLM oder Fehler greift der deterministische Fallback-Satz.
    """
    angle = aufhaenger_angle(lead, angebot_typ)
    if angle is None:
        return ""

    if llm is not None:
        prompt = _baue_prompt(angle, angebot_typ, firma=firma, branche=branche,
                              ansprechpartner=ansprechpartner)
        try:
            satz = (llm(prompt) or "").strip()
        except Exception:
            satz = ""
        if satz:
            return _saeubern(satz)

    return _saeubern(angle.fallback_satz)


def _saeubern(satz: str) -> str:
    """Entfernt versehentliche Anrede/Signatur-Reste — der Aufhänger ist NUR der Satz."""
    satz = (satz or "").strip().strip('"').strip()
    # Eine Aufhänger-Beobachtung ist 1–2 Sätze; harte Obergrenze gegen Ausreißer.
    return satz[:400].strip()


_SYSTEM_LEITLINIE = (
    "Du bist ein erfahrener B2B-Verkaufspsychologe und Texter. Du schreibst auf "
    "Deutsch, in der Sie-Form, direkt und ohne Floskeln oder Übertreibung. "
    "Du formulierst AUSSCHLIESSLICH aus den gelieferten Fakten – nichts erfinden, "
    "nichts behaupten, was nicht belegt ist."
)

_AUFGABE = {
    "hiring_sales": (
        "Schreibe 1–2 Sätze als Gesprächseinstieg, der zeigt, dass dir aufgefallen "
        "ist, dass die Firma gerade Vertrieb/Neukundengewinnung priorisiert. Mach "
        "daraus eine knappe, respektvolle Beobachtung – kein Lob, keine Floskel."
    ),
    "growth": (
        "Schreibe 1–2 Sätze als Einstieg, der die erkennbare Wachstums-/"
        "Expansionsphase der Firma aufgreift und sanft mit dem Bedarf an planbaren "
        "Erstgesprächen verbindet."
    ),
    "website_schwaeche": (
        "Schreibe 1–2 Sätze, die die konkret beobachteten Schwachstellen der Website "
        "sachlich benennen und klar machen, dass dadurch Anfragen verloren gehen. "
        "Sachlich, nicht abwertend."
    ),
    # Versicherungs-Angles: Trigger benennen, sanft auf die Deckungslücke überleiten,
    # KEINE Panikmache, kein Verkaufsdruck, kein Lob.
    "vs_hiring": (
        "Schreibe 1–2 Sätze als Gesprächseinstieg, der aufgreift, dass die Firma gerade "
        "einstellt, und sanft auf die betriebliche Altersvorsorge inklusive der 15-%-"
        "Zuschusspflicht für neue Mitarbeiter überleitet. Sachlich, keine Panikmache."
    ),
    "vs_benefits": (
        "Schreibe 1–2 Sätze, die aufgreifen, dass die Firma mit Benefits wirbt, und "
        "andeuten, dass die bAV/bKV dabei oft nicht optimal aufgesetzt ist. Respektvoll, "
        "kein Verkaufsdruck."
    ),
    "vs_fuhrpark": (
        "Schreibe 1–2 Sätze, die aufgreifen, dass die Firma Fahrer/Außendienst/Fuhrpark "
        "hat, und sachlich auf mögliche Lücken im Schadenfall (inkl. Insassen-/"
        "Gruppenunfall) hinweisen. Nüchtern, ohne Drohung."
    ),
    "vs_standort": (
        "Schreibe 1–2 Sätze, die aufgreifen, dass die Firma einen neuen Standort "
        "aufbaut, und darauf hinweisen, dass die Versicherungen oft noch auf altem "
        "Stand laufen. Sachlich."
    ),
    "vs_produktion": (
        "Schreibe 1–2 Sätze, die aufgreifen, dass die Firma Produktion/Maschinen/Lager "
        "betreibt, und nüchtern klarmachen, dass ein Betriebsausfall teuer werden kann. "
        "Keine Angstmache."
    ),
    "vs_cyber": (
        "Schreibe 1–2 Sätze, die aufgreifen, dass IT/Kundendaten zentral sind, und auf "
        "Cyber als wachsendes Pflichtthema (NIS2) überleiten. Sachlich, kein Alarmismus."
    ),
}


def _baue_prompt(angle: Aufhaenger, angebot_typ: str, *, firma: str, branche: str,
                ansprechpartner: str) -> str:
    aufgabe = _AUFGABE.get(angle.typ, _AUFGABE["hiring_sales"])
    fakten_zeilen = [f"- {k}: {v}" for k, v in angle.fakten.items() if v]
    kontext = [
        f"Angebot: {angebot_typ}",
        f"Firma: {firma}" if firma else "",
        f"Branche: {branche}" if branche else "",
        f"Ansprechpartner: {ansprechpartner}" if ansprechpartner else "",
    ]
    return (
        f"{_SYSTEM_LEITLINIE}\n\n"
        f"AUFGABE: {aufgabe}\n\n"
        "KONTEXT:\n" + "\n".join(z for z in kontext if z) + "\n\n"
        "BELEGTE FAKTEN (nur diese verwenden):\n" + "\n".join(fakten_zeilen) + "\n\n"
        "Gib NUR die 1–2 Sätze zurück. Keine Anrede, keine Grußformel, keine "
        "Signatur, keine Anführungszeichen."
    )


# ─── Standard-LLM (OpenAI) — lazy, nie beim Import ──────────────────────────

def standard_llm() -> Optional[LLM]:
    """Gibt ein OpenAI-Callable zurück, oder None wenn kein Key gesetzt ist.

    Liest OPENAI_API_KEY aus der Umgebung (die der product-Layer aus der
    Engine-.env lädt). Der Key wird NIE geloggt oder ausgegeben. Ist kein Key
    da, gibt diese Funktion None → die Aufrufer fallen auf den Regel-Satz zurück.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.environ.get("AUFHAENGER_LLM_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

    def _call(prompt: str) -> str:
        try:
            from openai import OpenAI  # type: ignore
        except Exception:
            return ""
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=160,
        )
        return (resp.choices[0].message.content or "").strip()

    return _call


# ─── Demo: Fallback-Aufhänger ohne LLM/Netz ──────────────────────────────────

if __name__ == "__main__":
    proben = [
        ("kundenagent", {"entdeckt_per_signal": "sales_hiring",
                          "signal_titel": "Sales Manager (m/w/d) Neukundengeschäft"}),
        ("akquise", {"entdeckt_per_signal": "growth_expansion",
                     "signal_titel": "Wir eröffnen einen zweiten Standort"}),
        ("website", {"website_schwaechen": ["langsam_mobil", "kein_cta"],
                     "website": "https://beispiel.de"}),
        ("kundenagent", {}),  # kein Signal → ""
    ]
    for angebot, lead in proben:
        txt = aufhaenger_text(lead, angebot, firma="Beispiel GmbH", branche="IT-Dienstleister")
        print(f"[{angebot}] {txt or '(kein Signal → generische Mail)'}")
