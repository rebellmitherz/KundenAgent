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


def _frische(lead: dict) -> tuple[float, str, Optional[int]]:
    """(Frische-Faktor 0.5–1.0, Label, Alter in Tagen) aus ``signal_alter_tage``.

    Defensiv: Modul fehlt / Wert kein int → neutral (1.0, "", None) = kein Abschlag."""
    tage = lead.get("signal_alter_tage")
    if not isinstance(tage, int):
        return 1.0, "", None
    try:
        from product.bridge import signal_freshness as _fr
        return _fr.frische_faktor(tage), _fr.frische_text(tage), tage
    except Exception:
        return 1.0, "", tage


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


def _signale_des_leads(lead: dict, primaer: str) -> list[str]:
    """Alle Signaltypen der Firma (Stapelung) — Fallback: nur das Primär-Signal."""
    roh = lead.get("signale")
    if isinstance(roh, (list, tuple)):
        out = [str(s).strip().lower() for s in roh if str(s).strip()]
    else:
        out = []
    if not out and primaer:
        out = [primaer]
    return list(dict.fromkeys(out))


def bewerten(lead: dict) -> dict:
    """Verdichtet die vorhandenen Lead-Felder zur Kaufbereitschafts-Analyse.

    Rückgabe: {score:int(0–100), stufe:str, gruende:list[str], beleg_titel, beleg_url}
    """
    signal_typ = (lead.get("entdeckt_per_signal") or "").strip().lower()
    signale = _signale_des_leads(lead, signal_typ)
    # Signalstärke = STÄRKSTES aller Signale der Firma (nicht nur das Primär-/Fit-
    # Signal). Eine Firma, die zugleich Terminierer sucht (1.0), verdient die 1.0 —
    # auch wenn ein anderes Signal den höheren Fit hatte.
    s_staerke = max((_signal_staerke(s) for s in signale), default=_signal_staerke(signal_typ))
    fit = _fit(lead)
    kontakt, phone, pers_mail = _kontakt_komponente(lead)
    frische_faktor, frische_label, alter_tage = _frische(lead)

    roh = _W_SIGNAL * s_staerke + _W_FIT * fit + _W_KONTAKT * kontakt
    # Frische-Faktor zuletzt: ein veraltetes Signal (Stelle vermutlich besetzt)
    # senkt die Kaufbereitschaft und damit die Stufe — frisch/unbekannt = neutral.
    score = int(round(max(0.0, min(1.0, roh)) * 100 * frische_faktor))

    # Heißgrad-Bonus (Signal-Stapelung): mehrere GLEICHZEITIGE Kaufsignale sind der
    # stärkste Beleg für akuten Bedarf. Gebündelt + gedeckelt, damit ein Lead nicht
    # allein durch Signalzahl nach oben rutscht. +8 je Zusatzsignal, max +20.
    extra = max(len(signale) - 1, 0)
    stapel_bonus = min(extra * 8, 20)
    score = min(100, score + stapel_bonus)

    if score >= 70:
        stufe = HOCH
    elif score >= 45:
        stufe = MITTEL
    else:
        stufe = NIEDRIG

    gruende: list[str] = []
    if extra >= 1:
        from product.bridge import signal_discovery as _sd
        labels = [_sd.SIGNAL_LABELS.get(s, s) for s in signale]
        gruende.append(f"🔥 {len(signale)} gleichzeitige Kaufsignale: {', '.join(labels)}")
    elif signal_typ:
        gruende.append(f"Kaufsignal: {_SIGNAL_WARUM.get(signal_typ, 'zeigt Kaufsignal')}")
    # Frische als erstklassiger Grund — frisch = Verkaufsargument, alt = ehrliche Warnung.
    if frische_label and isinstance(alter_tage, int):
        if alter_tage <= 14:
            gruende.append(f"Signal frisch: Anzeige {frische_label}")
        elif alter_tage > 90:
            gruende.append(f"⚠ Anzeige {frische_label} — Aktualität vor Ansprache prüfen")
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
        "alter_tage": alter_tage,
        "frische_text": frische_label,
    }


def anreichern(leads: list[dict]) -> None:
    """Heftet je Lead den Kaufbereitschafts-Block an (defensiv, in-place)."""
    for lead in leads or []:
        try:
            r = bewerten(lead)
        except Exception:
            r = {"score": 0, "stufe": NIEDRIG, "gruende": [], "beleg_titel": "",
                 "beleg_url": "", "alter_tage": None, "frische_text": ""}
        lead["kaufbereitschaft_score"] = r["score"]
        lead["kaufbereitschaft_stufe"] = r["stufe"]
        lead["kaufbereitschaft_gruende"] = r["gruende"]
        lead["kaufbereitschaft_beleg_titel"] = r["beleg_titel"]
        lead["kaufbereitschaft_beleg_url"] = r["beleg_url"]
        # Frische sichtbar machen (Verkaufsargument bzw. Warnung auf der Lieferkarte).
        lead["signal_alter_tage"] = r.get("alter_tage")
        lead["signal_frische_text"] = r.get("frische_text", "")
