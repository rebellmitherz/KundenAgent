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
    # Versicherungs-Signale (Reihenfolge = Gewichtung für „die Bayerische").
    # vs_hiring am stärksten: führt zu bAV (wiederkehrend) + bAV-Zuschusspflicht.
    "vs_hiring": 0.9,
    "vs_benefits": 0.8,
    "vs_fuhrpark": 0.7,
    "vs_standort": 0.65,
    "vs_produktion": 0.6,
    "vs_cyber": 0.6,
}

# Warum der Signaltyp ein Kaufsignal ist (Analyse-Zeile, kundenlesbar).
_SIGNAL_WARUM: dict[str, str] = {
    "appointment_setter": "sucht aktiv Terminierer/SDR — investiert gerade in Outbound",
    "sales_hiring": "stellt Vertrieb ein — Budget + Bedarf jetzt",
    "leadership_hiring": "holt Vertriebs-/Marketing-Leitung — baut Go-to-Market aus",
    "growth_expansion": "wächst / baut Team aus",
    "marketing_hiring": "investiert in Marketing / Leadgen",
    "new_location": "eröffnet Standort / expandiert",
    # Versicherungs-Signale: je eine Veränderung, die eine Deckungslücke aufreißt.
    "vs_hiring": "stellt ein — bAV-Zuschusspflicht (15 %) für neue Mitarbeiter mitgewachsen?",
    "vs_benefits": "wirbt mit Benefits — bAV/bKV oft nicht optimal aufgebaut, Check lohnt",
    "vs_fuhrpark": "Fuhrpark/Fahrer — bei Flotten oft Lücken im Schadenfall (Insassen-/Gruppenunfall)",
    "vs_standort": "eröffnet neuen Standort — Versicherungen laufen oft noch auf altem Stand",
    "vs_produktion": "Produktion/Maschinen — ein Betriebsausfall kann mehr kosten als die Jahresprämie",
    "vs_cyber": "IT-/Cyber-Risiko sichtbar — Cyber wird Pflichtthema (NIS2)",
}

# Gewichte (Summe 1): Signalstärke dominiert (= der Kaufbereitschafts-Kern),
# dann Passung, dann Erreichbarkeit.
_W_SIGNAL = 0.45
_W_FIT = 0.25
_W_KONTAKT = 0.30

# E-Mail-Rang der Engine: „D"/E/F = missing/unverifiziert = Fake/Bounce-Klasse
# (kein nutzbarer Mail-Kanal). A=personal, B=partial, C=generic_mailbox.
_RANG_FAKE = frozenset({"d", "e", "f"})

# Numerischer Rang der Stufen — fürs Deckeln (nur senken, nie anheben).
_STUFE_RANG = {HOCH: 3, MITTEL: 2, NIEDRIG: 1}

# Sammel-/Rollen-Postfächer — eine persönliche Adresse ist mehr wert als info@.
# Bewusst breit: eine Adresse fälschlich „persönlich" zu nennen kostet beim
# Kunden Glaubwürdigkeit. Lieber konservativ (siehe ist_persoenliche_mail).
_GENERISCHE_MAIL_PREFIXES = {
    "info", "kontakt", "contact", "mail", "email", "mails", "office", "buero", "bureau",
    "hello", "hallo", "moin", "post", "service", "support", "willkommen", "welcome",
    "anfrage", "anfragen", "kundenservice", "kundendienst", "vertrieb", "sales",
    "team", "zentrale", "empfang", "reception", "sekretariat", "verwaltung",
    "buchhaltung", "rechnung", "rechnungen", "finance", "finanzen", "accounting",
    "einkauf", "bestellung", "bestellungen", "order", "shop", "verkauf", "beratung",
    "presse", "press", "media", "marketing", "werbung", "pr",
    "jobs", "job", "karriere", "career", "careers", "bewerbung", "bewerbungen",
    "recruiting", "hr", "personal", "datenschutz", "dsgvo", "privacy", "impressum",
    "webmaster", "admin", "noreply", "donotreply", "newsletter", "news",
    "abo", "praxis", "kanzlei", "termin", "termine", "anmeldung", "reservierung",
    "reservation", "booking", "billing", "invoice", "feedback", "kontaktformular",
}


def _signal_staerke(signal_typ: str) -> float:
    return _SIGNAL_STAERKE.get((signal_typ or "").strip().lower(), 0.5)


def _fit(lead: dict) -> float:
    try:
        f = float(lead.get("signal_fit_score") or 0.0)
    except (TypeError, ValueError):
        f = 0.0
    return max(0.0, min(1.0, f))


def _local_tokens(local: str) -> list[str]:
    """Zerlegt den local-part (vor dem @) an Trennern/Ziffern in Namens-Tokens."""
    for sep in ".-_+":
        local = local.replace(sep, " ")
    for d in "0123456789":
        local = local.replace(d, " ")
    return [t for t in local.split() if t]


def ist_persoenliche_mail(email: str, contact_name: str = "") -> bool:
    """True NUR, wenn die Adresse plausibel einen Personennamen trägt.

    Konservativ — eine falsche „persönlich"-Behauptung kostet Glaubwürdigkeit:
      • jedes Rollenwort im local-part (info, kontakt, vertrieb, service, …,
        auch in `info.berlin@`/`vertrieb-nord@`) ⇒ NICHT persönlich.
      • deckt sich der local-part mit dem bekannten Ansprechpartner ⇒ persönlich.
      • Muster `vorname.nachname@` (≥2 alphabetische Tokens) ⇒ persönlich.
      • alles andere (bloßes `markus@`, `t.online@`, Kürzel) ⇒ NICHT persönlich.
    """
    email = (email or "").strip().lower()
    if "@" not in email:
        return False
    local = email.split("@", 1)[0].strip()
    toks = _local_tokens(local)
    if not toks:
        return False
    if local in _GENERISCHE_MAIL_PREFIXES or any(t in _GENERISCHE_MAIL_PREFIXES for t in toks):
        return False
    name = (contact_name or "").lower()
    for ch in ".,-_/\\":
        name = name.replace(ch, " ")
    nt = [t for t in name.split() if len(t) >= 3]
    if nt and any(t in toks for t in nt):
        return True
    alpha = [t for t in toks if t.isalpha() and len(t) >= 2]
    return len(alpha) >= 2


# Rückwärtskompatibler Alias (alter Name).
def _hat_persoenliche_mail(email: str, contact_name: str = "") -> bool:
    return ist_persoenliche_mail(email, contact_name)


# Dt. Mobilfunk-Vorwahlen (015x/016x/017x bzw. +4915…). Eine Mobilnummer ist
# eher ein Direktkontakt — eine Festnetz-Zentrale NICHT als „direkt" verkaufen.
def ist_mobilnummer(phone: str) -> bool:
    p = (phone or "").strip()
    if not p:
        return False
    digits = "".join(c for c in p if c.isdigit())
    if p.lstrip().startswith("+"):
        if digits.startswith("49"):
            digits = digits[2:]
        else:
            return False  # nur DE-Mobil sicher erkennbar
    elif digits.startswith("0049"):
        digits = digits[4:]
    digits = digits.lstrip("0")
    return digits.startswith(("15", "16", "17"))


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
    name = lead.get("contact_full_name") or lead.get("managing_director") or lead.get("contact_person") or ""
    pers_mail = ist_persoenliche_mail(lead.get("email") or lead.get("contact_email") or "", name)
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


def _stufe_deckeln(stufe: str, obergrenze: Optional[str]) -> str:
    """Senkt ``stufe`` auf ``obergrenze`` — hebt NIE an (Deckel, kein Hebel)."""
    if not obergrenze:
        return stufe
    if _STUFE_RANG.get(stufe, 1) > _STUFE_RANG.get(obergrenze, 2):
        return obergrenze
    return stufe


def _engine_deckelung(lead: dict, score: int, *, phone: bool, pers_mail: bool):
    """Härtet den Score am Engine-Urteil (Schritt 2 Premium-Gate).

    Ein heißes Signal allein macht einen Lead nicht sendefähig: ``ready_to_send=no``,
    ein Fake/Bounce-E-Mail-Rang, ``do_not_contact`` oder eine reine Rollen-/Sammel-
    Mail ohne Telefon dürfen NIE als „hoch" durchgehen. Greift nur, wenn das jeweilige
    Feld wirklich gesetzt ist (fehlt es = kein Abschlag — bleibt rückwärtskompatibel).

    Rückgabe: (gesenkter Score, harte Stufen-Obergrenze|None, Warn-Gründe).
    """
    gruende: list[str] = []
    obergrenze: Optional[str] = None

    if lead.get("do_not_contact"):                       # hart: nicht ansprechen
        score = min(score, 25)
        obergrenze = NIEDRIG
        gruende.append("⚠ Engine: do_not_contact — nicht ansprechen")

    rts = str(lead.get("ready_to_send") or "").strip().lower()
    if rts == "no":                                      # Engine sagt: nicht sendefähig
        score = min(score, 60)
        if obergrenze != NIEDRIG:
            obergrenze = MITTEL
        block = str(lead.get("ready_to_send_block_reason") or "").strip()
        gruende.append("⚠ Engine: noch nicht sendefähig" + (f" ({block})" if block else ""))

    rang = str(lead.get("email_quality_rank") or "").strip().lower()
    if rang in _RANG_FAKE:                                # missing/Fake-Bounce-Mail
        score = max(0, score - 15)
        gruende.append(f"⚠ E-Mail-Qualität niedrig (Rang {rang.upper()} — unverifiziert/Fake-Bounce)")

    mail = str(lead.get("email") or lead.get("contact_email") or "").strip()
    if mail and not pers_mail and not phone:             # nur Rollen-Mail, kein Telefon
        if obergrenze != NIEDRIG:
            obergrenze = MITTEL
        gruende.append("⚠ nur Sammel-/Rollen-Mail, kein Telefon — schwacher Kontakt")

    return score, obergrenze, gruende


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

    # Engine-Urteil härtet den Score (Schritt 2): ready_to_send=no, Fake-Mail-Rang,
    # do_not_contact und reine Rollen-Mail ohne Telefon dürfen nie „hoch" tragen.
    score, obergrenze, engine_gruende = _engine_deckelung(
        lead, score, phone=phone, pers_mail=pers_mail)

    if score >= 70:
        stufe = HOCH
    elif score >= 45:
        stufe = MITTEL
    else:
        stufe = NIEDRIG
    stufe = _stufe_deckeln(stufe, obergrenze)

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
    tel_roh = (lead.get("phone") or lead.get("phone_clean") or lead.get("contact_phone") or "").strip()
    mobil = ist_mobilnummer(tel_roh)
    tel_label = "Mobilnummer (Direktkontakt)" if mobil else "Telefonnummer vorhanden"
    if phone and pers_mail:
        gruende.append(f"{tel_label} + persönliche E-Mail")
    elif phone:
        gruende.append(tel_label)
    elif pers_mail:
        gruende.append("Persönliche E-Mail-Adresse")

    # Engine-Warnungen zuerst — eine ehrliche Warnung ist wichtiger als ein Lob.
    gruende = engine_gruende + gruende

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
