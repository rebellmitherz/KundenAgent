"""Kaufbereitschaft (Readiness) — bewertet je Signal-Lead, wie kaufbereit die
Firma ist, und macht es als *verkaufbare* Analyse lesbar.

Warum diese Schicht existiert
------------------------------
Das 1k-Produkt („50 qualifizierte Signal-Leads + Kaufbereitschafts-Analyse")
verkauft nicht nur Kontakte, sondern *bewertete* Leads. Die Engine liefert die
Rohsignale bereits an jeden Lead (Signaltyp, Fit, Kontaktqualität, Beleg-URL) —
diese Schicht verdichtet sie zu einem **Score (0–100) + Stufe (hoch/mittel/
niedrig) + kurzen, ehrlichen Gründen + Beleg**, ohne eine neue Bewertung zu
erfinden. Sie liest nur, was Discovery/Scoring/Enrich schon entschieden haben.

Muster wie im übrigen Code: **rein deterministisch** — kein Netz, kein LLM, voll
testbar. Defensiv: ein kaputter Lead darf die Suche nie kippen.
"""
from __future__ import annotations

HOCH = "hoch"
MITTEL = "mittel"
NIEDRIG = "niedrig"

# Intrinsische Kaufsignal-Stärke je Signaltyp (0..1): wie unmittelbar belegt der
# Typ akuten Bedarf + Budget? „sucht Terminierer/SDR" = investiert JETZT in
# Outbound (heißestes Signal); „stellt Vertrieb ein" dicht dahinter.
_SIGNAL_STAERKE: dict[str, float] = {
    "appointment_setter": 1.0,
    "sales_hiring": 0.9,
    "leadership_hiring": 0.8,
    "growth_expansion": 0.65,
    "marketing_hiring": 0.55,
    "new_location": 0.55,
}

# Warum der Signaltyp ein Kaufsignal ist (Analyse-Zeile, kundenlesbar).
_SIGNAL_WARUM: dict[str, str] = {
    "appointment_setter": "sucht aktiv Terminierer/SDR — investiert gerade in Outbound",
    "sales_hiring": "stellt Vertrieb ein — Budget + Bedarf jetzt",
    "leadership_hiring": "holt Vertriebs-/Marketing-Leitung — baut Go-to-Market aus",
    "growth_expansion": "wächst / baut Team aus",
    "marketing_hiring": "investiert in Marketing / Leadgen",
    "new_location": "eröffnet Standort / expandiert",
}

# Gewichte (Summe 1): Signalstärke dominiert (= der Kaufbereitschafts-Kern),
# dann Passung, dann Erreichbarkeit.
_W_SIGNAL = 0.45
_W_FIT = 0.25
_W_KONTAKT = 0.30

# Sammel-Postfächer — eine persönliche Adresse ist mehr wert als info@.
_GENERISCHE_MAIL_PREFIXES = (
    "info", "kontakt", "mail", "office", "hello", "hallo", "post",
    "contact", "service", "support", "willkommen", "anfrage",
)


def _signal_staerke(signal_typ: str) -> float:
    return _SIGNAL_STAERKE.get((signal_typ or "").strip().lower(), 0.5)


def _fit(lead: dict) -> float:
    try:
        f = float(lead.get("signal_fit_score") or 0.0)
    except (TypeError, ValueError):
        f = 0.0
    return max(0.0, min(1.0, f))


def _hat_persoenliche_mail(email: str) -> bool:
    email = (email or "").strip().lower()
    if "@" not in email:
        return False
    return email.split("@", 1)[0] not in _GENERISCHE_MAIL_PREFIXES


def _kontakt_komponente(lead: dict) -> tuple[float, bool, bool]:
    """(Kontakt-Komponente 0..1, hat_telefon, hat_persoenliche_mail)."""
    try:
        cq = float(lead.get("contact_quality_score") or 0)
    except (TypeError, ValueError):
        cq = 0.0
    cq = max(0.0, min(1.0, cq / 100.0))
    phone = bool((lead.get("phone") or lead.get("phone_clean") or lead.get("contact_phone") or "").strip())
    pers_mail = _hat_persoenliche_mail(lead.get("email") or lead.get("contact_email") or "")
    komp = cq * 0.6 + (0.2 if phone else 0.0) + (0.2 if pers_mail else 0.0)
    return max(0.0, min(1.0, komp)), phone, pers_mail


def bewerten(lead: dict) -> dict:
    """Verdichtet die vorhandenen Lead-Felder zur Kaufbereitschafts-Analyse.

    Rückgabe: {score:int(0–100), stufe:str, gruende:list[str], beleg_titel, beleg_url}
    """
    signal_typ = (lead.get("entdeckt_per_signal") or "").strip().lower()
    s_staerke = _signal_staerke(signal_typ)
    fit = _fit(lead)
    kontakt, phone, pers_mail = _kontakt_komponente(lead)

    roh = _W_SIGNAL * s_staerke + _W_FIT * fit + _W_KONTAKT * kontakt
    score = int(round(max(0.0, min(1.0, roh)) * 100))

    if score >= 70:
        stufe = HOCH
    elif score >= 45:
        stufe = MITTEL
    else:
        stufe = NIEDRIG

    gruende: list[str] = []
    if signal_typ:
        gruende.append(f"Kaufsignal: {_SIGNAL_WARUM.get(signal_typ, 'zeigt Kaufsignal')}")
    if fit >= 0.7:
        gruende.append(f"Hohe Passung zur Zielgruppe (Fit {fit:.2f})")
    elif fit >= 0.45:
        gruende.append(f"Solide Passung (Fit {fit:.2f})")
    if phone and pers_mail:
        gruende.append("Direkt erreichbar: Telefon + persönliche E-Mail")
    elif phone:
        gruende.append("Telefon vorhanden — direkt anrufbar")
    elif pers_mail:
        gruende.append("Persönliche E-Mail-Adresse gefunden")

    return {
        "score": score,
        "stufe": stufe,
        "gruende": gruende[:4],
        "beleg_titel": (lead.get("signal_titel") or "").strip(),
        "beleg_url": (lead.get("signal_quelle_url") or "").strip(),
    }


def anreichern(leads: list[dict]) -> None:
    """Heftet je Lead den Kaufbereitschafts-Block an (defensiv, in-place)."""
    for lead in leads or []:
        try:
            r = bewerten(lead)
        except Exception:
            r = {"score": 0, "stufe": NIEDRIG, "gruende": [], "beleg_titel": "", "beleg_url": ""}
        lead["kaufbereitschaft_score"] = r["score"]
        lead["kaufbereitschaft_stufe"] = r["stufe"]
        lead["kaufbereitschaft_gruende"] = r["gruende"]
        lead["kaufbereitschaft_beleg_titel"] = r["beleg_titel"]
        lead["kaufbereitschaft_beleg_url"] = r["beleg_url"]
