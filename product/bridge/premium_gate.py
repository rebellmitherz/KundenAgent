"""Premium-Gate — die harte Qualitäts-Schranke VOR der Ausgabe.

Warum diese Schicht existiert
------------------------------
Das 1k-Produkt verkauft „50 qualifizierte Signal-Leads = 1.000 €" (≈ 20 € je
Lead). Der bisherige Output ist zu weich: Im letzten echten Lauf standen 33/39
Leads auf „hoch", obwohl die Engine selbst nur 4 als ``ready_to_send=yes``
einstufte. Ein Käufer, der dafür 20 € zahlt, merkt das sofort.

Dieses Gate dreht den Spieß um: **lieber 8 echte Top-Leads als 39 wackelige.**
Es liest nur, was Discovery/Scoring/Enrich/Readiness bereits an den Lead
geschrieben haben (rein deterministisch, kein Netz, kein LLM) und vergibt eine
von drei Klassen:

  • ``PREMIUM`` — alle harten Regeln erfüllt, darf ausgegeben werden und „hoch" tragen.
  • ``REVIEW``  — grenzwertig, vor Ausgabe manuell prüfen, nie automatisch „hoch".
  • ``REJECT``  — harter K.-o.-Grund, fliegt raus.

Leitplanken (wie im übrigen Product-Layer):
  • **Engine read-only** — ``b2bbot/`` wird nicht angefasst; das Gate *überschreibt*
    die weiche Engine-Einstufung im Product-Layer.
  • **Defensiv** — ein kaputter Lead darf die Suche nie kippen; im Zweifel REVIEW.
  • Baut auf den schon vorhandenen, robusten Bausteinen auf
    (``signal_readiness.ist_persoenliche_mail`` / ``ist_mobilnummer``,
    ``signal_contact_enrich._ist_mull_name``) — nichts davon wird neu erfunden.
"""
from __future__ import annotations

from product.bridge.signal_readiness import ist_persoenliche_mail, ist_mobilnummer

PREMIUM = "PREMIUM"
REVIEW = "REVIEW"
REJECT = "REJECT"

HOCH = "hoch"
MITTEL = "mittel"
NIEDRIG = "niedrig"

# Frische-Grenze: ein Beleg älter als das ist „kalt" (Stelle vermutlich besetzt) —
# max REVIEW. Unbekanntes Datum bleibt erlaubt, deckelt aber auf „mittel".
_FRISCH_MAX_TAGE = 90

# Platzhalter-/Demo-Domains: eine Website, die so aussieht, ist keine echte Firma.
_PLATZHALTER_DOMAIN_TOKENS = (
    "yourdomain", "example.", "example-", "musterfirma", "mustermann",
    "musterfrau", "beispiel", "company.com", "firmenname", "test.de", "domain.de",
    "ihre-domain", "ihredomain", "deine-domain",
)

# Hostteile, die KEINE eigene Firmen-Website sind (nur ein Profil).
_KEINE_WEBSITE_HOSTS = ("linkedin.", "xing.", "facebook.", "instagram.", "indeed.")

# Artefakt-Tokens für FIRMENNAMEN (Scraper-/Platzhalter-Müll). Bewusst eng, damit
# echte Firmen nicht fälschlich fliegen. Der tiefere Filter folgt in Schritt 3.
_FIRMA_ARTEFAKT_TOKENS = frozenset({
    "firmenname", "mustermann", "musterfrau", "musterfirma", "beispielfirma",
    "amercia",  # echter Tippfehler-Artefakt aus dem Lauf ("Amercia Inc")
})

# Token, das in einem PERSONEN-Namen ein Artefakt verrät (Titel-/Rechtsform-Fragment).
_PERSON_ARTEFAKT_TOKENS = frozenset({
    "dipl", "inc", "gmbh", "ag", "kg", "ohg", "ug", "mbh", "firmenname", "b2b",
})

# Scrape-Überschriften/Rechtstext-Fragmente, die in einem echten Firmennamen nie
# vorkommen — der Scraper hat eine Seitenüberschrift mit dem Namen verklebt
# (echter Lauf: „GmbH Unternehmensangaben ventx GmbH").
_FIRMA_HEADING_ARTEFAKT = frozenset({
    "unternehmensangaben", "impressum", "kontaktformular", "seitennavigation",
    "datenschutzerklärung", "datenschutzerklarung", "startseite", "cookieeinstellungen",
})
# Rechtsform als ERSTES Wort = Artefakt: ein echter Name trägt die Rechtsform als
# Suffix („ventx GmbH"), nie als Präfix („GmbH … ventx GmbH").
_FIRMA_RECHTSFORM_LEAD = frozenset({
    "gmbh", "ag", "kg", "ohg", "ug", "mbh", "kgaa", "gbr", "llc", "ltd", "inc",
})

# Branchenfremde Rollen-/Funktionswörter — als „Zielbranche" untauglich (genau der
# Defekt: „Vertrieb" als Zielgruppe matcht jede Firma). Trennt ICP von Signal.
_ROLLEN_WORTE = frozenset({
    "vertrieb", "sales", "verkauf", "verkaeufer", "verkäufer", "akquise",
    "akquisition", "kaltakquise", "sdr", "bdr", "terminierer", "appointment",
    "setter", "außendienst", "aussendienst", "innendienst", "account",
    "businessdevelopment", "vertriebler", "telefonist", "telesales",
})

# E-Mail-Rang der Engine. „D" = missing_email/unverifiziert = Fake/Bounce-Klasse.
_RANG_FAKE = frozenset({"d", "e", "f"})
# Engine-Block-Gründe, die ein hartes K.-o. sind (echte Bounce-/Risiko-Mail).
_BLOCK_HART = ("invalid", "risky", "bounce", "do_not_contact", "blacklist")

# „No-Sales"-Postfächer: Adressen, die für eine Akquise wertlos sind, weil dort kein
# Entscheider sitzt (Bewerbungen, Technik, Rechtstext, Automaten). Eine Rollenmail
# wie info@/office@ ist nur „nicht persönlich"; DIESE hier sind aktiv falsch — sie
# dürfen nie PREMIUM tragen, und als EINZIGER Kontakt ist der Lead nicht sendefähig.
_MAIL_HART_RAUS = frozenset({
    "jobs", "job", "karriere", "career", "careers", "bewerbung", "bewerbungen",
    "recruiting", "hr", "personal", "noreply", "noreplay", "donotreply", "no-reply",
    "newsletter", "datenschutz", "dsgvo", "privacy", "presse", "press", "media",
    "webmaster", "admin", "abuse", "postmaster", "helpdesk", "support-ticket",
})


def _norm(text: object) -> str:
    return str(text or "").strip()


def _tokens(text: str) -> set[str]:
    out: list[str] = []
    cur = []
    for ch in (text or "").lower():
        if ch.isalnum():
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return set(out)


# ── Regel 1: echtes Signal + Beleg ──────────────────────────────────────────
def _beleg_url(lead: dict) -> str:
    u = _norm(lead.get("signal_quelle_url"))
    if u:
        return u
    belege = lead.get("signal_belege")
    if isinstance(belege, (list, tuple)):
        for b in belege:
            if isinstance(b, dict):
                bu = _norm(b.get("quelle_url") or b.get("url"))
                if bu:
                    return bu
    return ""


# ── Regel 3: echte Website ──────────────────────────────────────────────────
def _ist_echte_website(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u:
        return False
    host = u
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0]
    if any(h in host for h in _KEINE_WEBSITE_HOSTS):
        return False
    # Platzhalter-Domains zentral aus dem Enrich-Filter (eine Wahrheit, Schritt 3).
    try:
        from product.bridge.signal_contact_enrich import _ist_platzhalter_domain
        platzhalter = _ist_platzhalter_domain(u)
    except Exception:
        platzhalter = any(tok in u for tok in _PLATZHALTER_DOMAIN_TOKENS)
    if platzhalter:
        return False
    return "." in host


# ── Regel 4: kein Artefakt in Firma/Name ────────────────────────────────────
def _ist_firma_artefakt(name: str) -> bool:
    n = _norm(name)
    if not n:
        return False
    # Zentraler Firmenname-Filter aus dem Enrich-Layer (eine Wahrheit, Schritt 3).
    try:
        from product.bridge.signal_contact_enrich import _ist_mull_firma
        if _ist_mull_firma(n):
            return True
    except Exception:
        pass
    toks = _tokens(n)
    if toks & _FIRMA_ARTEFAKT_TOKENS:
        return True
    # Scrape-Überschrift im Namen („… Unternehmensangaben …", „Impressum …").
    if toks & _FIRMA_HEADING_ARTEFAKT:
        return True
    # Rechtsform als erstes Wort („GmbH Unternehmensangaben ventx GmbH").
    woerter = n.split()
    if woerter and woerter[0].strip(".,").lower() in _FIRMA_RECHTSFORM_LEAD:
        return True
    # „Firmenname B2B" o. Ä. — reine Platzhalter-Kombination.
    if "b2b" in toks and ("firmenname" in toks or "musterfirma" in toks):
        return True
    return False


def _ist_person_artefakt(name: str) -> bool:
    n = _norm(name)
    if not n:
        return False
    try:
        from product.bridge.signal_contact_enrich import _ist_mull_name
        if _ist_mull_name(n):
            return True
    except Exception:
        pass
    return bool(_tokens(n) & _PERSON_ARTEFAKT_TOKENS)


# ── Regel 5: belastbarer Kontakt ────────────────────────────────────────────
def _telefon(lead: dict) -> str:
    return _norm(lead.get("phone") or lead.get("phone_clean") or lead.get("contact_phone"))


def _mail(lead: dict) -> str:
    return _norm(lead.get("email") or lead.get("contact_email"))


def _kontakt_lage(lead: dict) -> dict:
    tel = _telefon(lead)
    mail = _mail(lead)
    name = (
        lead.get("contact_full_name") or lead.get("managing_director")
        or lead.get("contact_person") or ""
    )
    pers = bool(mail) and ist_persoenliche_mail(mail, name)
    local = mail.split("@", 1)[0].lower() if "@" in mail else ""
    hart_raus = (not pers) and bool(_tokens(local) & _MAIL_HART_RAUS)
    # Echter Ansprechpartner = Name vorhanden UND kein Artefakt/Funktion/Abteilung.
    name_clean = (name or "").strip()
    try:
        from product.bridge.signal_contact_enrich import _ist_mull_name
        name_artefakt = bool(name_clean) and _ist_mull_name(name_clean)
    except Exception:
        name_artefakt = False
    hat_echten_ap = bool(name_clean) and not name_artefakt
    return {
        "hat_telefon": bool(tel),
        "ist_mobil": ist_mobilnummer(tel),
        "hat_mail": bool(mail),
        "persoenliche_mail": pers,
        "nur_rollen_mail": bool(mail) and not pers,
        "mail_hart_raus": hart_raus,
        "mail_prefix": local,
        "hat_echten_ap": hat_echten_ap,
        "name_artefakt": name_artefakt,
        "kein_kontakt": not tel and not mail,
    }


# ── Regel 7: echter ICP-Fit gegen die Zielbranche ───────────────────────────
def _ist_rollenwort(text: str) -> bool:
    # Zentrale Wahrheit aus signal_discovery (Intake-Trennung, Schritt 5); Fallback
    # auf die lokale Liste, falls der Import scheitert (Defensive).
    try:
        from product.bridge.signal_discovery import ist_rollenwort as _ir
        return _ir(text)
    except Exception:
        toks = _tokens(text)
        return bool(toks) and toks.issubset(_ROLLEN_WORTE | {"in", "im", "fuer", "für"})


def _icp_fit(lead: dict, zielbranche: str) -> tuple[str, str]:
    """('ok'|'fail'|'unbestimmt', grund)."""
    zb = _norm(zielbranche)
    if not zb or _ist_rollenwort(zb):
        return "unbestimmt", (
            f"ICP-Fit nicht prüfbar: Zielbranche „{zb or '—'}" + "“ ist ein Rollen-/"
            "Funktionswort, keine Branche (Intake-Trennung nötig, Schritt 5)"
        )
    text = " ".join(
        _norm(lead.get(k)) for k in
        ("industry", "industry_group", "description", "search_snippet", "company_name")
    ).lower()
    zb_toks = {t for t in _tokens(zb) if len(t) >= 3}
    if zb_toks and zb_toks & _tokens(text):
        return "ok", ""
    return "fail", f"Branche passt nicht zur Zielbranche „{zb}“"


# ── Hauptbewertung ──────────────────────────────────────────────────────────
def bewerten_premium(lead: dict, *, zielbranche: str = "", icp_breit: bool = False) -> dict:
    """Bewertet einen Signal-Lead gegen die harten Premium-Regeln.

    ``icp_breit`` (z. B. für „Versicherungsleads"): der ICP ist bewusst breit
    („gewerblicher Mittelstand mit Trigger") — dann qualifiziert das Kaufsignal,
    nicht eine enge Branche. Regel 7 darf in dem Fall NICHT wegen Branchen-
    Abweichung rejecten/blocken. Alle anderen harten Regeln bleiben in Kraft.

    Rückgabe::

        {
          "klasse": "PREMIUM"|"REVIEW"|"REJECT",
          "gruende": [str, ...],     # menschenlesbare Begruendung je Treffer
          "abzug": int,              # informativ: Summe der Punktabzüge
          "stufe_cap": "hoch"|"mittel"|"niedrig",  # max erlaubte Kaufbereitschaft
          "kills": [str, ...],       # harte K.-o.-Gründe (→ REJECT)
          "premium_miss": [str, ...] # weiche Gründe, die PREMIUM verhindern (→ REVIEW)
        }

    Defensiv: jeder unerwartete Fehler endet als REVIEW (nie als stiller PREMIUM).
    """
    try:
        return _bewerten(lead, zielbranche, icp_breit=icp_breit)
    except Exception as exc:  # pragma: no cover - reine Absicherung
        return {
            "klasse": REVIEW, "gruende": [f"Gate-Fehler, manuell prüfen: {exc}"],
            "abzug": 50, "stufe_cap": MITTEL, "kills": [], "premium_miss": ["gate_fehler"],
        }


def _bewerten(lead: dict, zielbranche: str, icp_breit: bool = False) -> dict:
    kills: list[str] = []          # → REJECT
    premium_miss: list[str] = []   # → max REVIEW
    gruende: list[str] = []
    abzug = 0

    # Regel 1 — echtes Signal + Beleg.
    signal = _norm(lead.get("entdeckt_per_signal"))
    beleg = _beleg_url(lead)
    if not signal:
        kills.append("kein Signal (entdeckt_per_signal leer) — kein Signal-Lead")
        abzug += 40
    elif not beleg:
        premium_miss.append("Signal ohne nachprüfbaren Beleg (keine Quelle-URL)")
        abzug += 15

    # Regel 3 — echte Website.
    if not _ist_echte_website(_norm(lead.get("website"))):
        kills.append("keine echte Firmen-Website (leer/Platzhalter/nur Profil)")
        abzug += 30

    # Regel 4 — kein Artefakt in Firma/Name.
    firma = _norm(lead.get("company_name") or lead.get("company_name_clean")
                  or lead.get("canonical_company_name"))
    # Enrich-Layer flaggt Firmenname-/Domain-Artefakte vorab (company_name_artefakt).
    if lead.get("company_name_artefakt") or _ist_firma_artefakt(firma):
        kills.append(f"Firmenname ist ein Artefakt/Platzhalter: „{firma}“")
        abzug += 30
    person = _norm(lead.get("contact_full_name") or lead.get("managing_director")
                   or lead.get("contact_person"))
    if person and _ist_person_artefakt(person):
        premium_miss.append(f"Ansprechpartner-Name wirkt wie ein Artefakt: „{person}“")
        abzug += 10

    # Regel 6 — Engine-Urteil respektieren.
    if lead.get("do_not_contact"):
        kills.append("do_not_contact gesetzt")
        abzug += 40
    block = _norm(lead.get("ready_to_send_block_reason")).lower()
    if any(b in block for b in _BLOCK_HART):
        kills.append(f"harter Sende-Block: {block}")
        abzug += 30
    rts = _norm(lead.get("ready_to_send")).lower()
    if rts == "no":
        premium_miss.append(
            "Engine: ready_to_send=no" + (f" ({block})" if block else ""))
        abzug += 20
    rang = _norm(lead.get("email_quality_rank")).lower()
    if rang in _RANG_FAKE:
        premium_miss.append(f"E-Mail-Rang „{rang.upper()}“ = Fake/Bounce-Klasse (kein nutzbarer Mail-Kanal)")
        abzug += 15

    # Regel 5 — belastbarer Kontakt.
    k = _kontakt_lage(lead)
    if k["kein_kontakt"]:
        kills.append("kein Kontakt (weder Telefon noch E-Mail)")
        abzug += 40
    elif k["mail_hart_raus"] and not k["hat_telefon"]:
        # einziger Kanal ist ein No-Sales-Postfach (jobs@/helpdesk@/noreply@ …) → nicht sendefähig.
        kills.append(f"einziger Kontakt ist ein No-Sales-Postfach „{k['mail_prefix']}@“ — nicht sendefähig")
        abzug += 30
    elif k["mail_hart_raus"]:
        # No-Sales-Postfach trotz Telefon: nie PREMIUM, der Mail-Kanal ist unbrauchbar.
        premium_miss.append(f"E-Mail ist ein No-Sales-Postfach „{k['mail_prefix']}@“ — nur telefonisch kontaktierbar")
        abzug += 15
    elif k["persoenliche_mail"]:
        # Persönliche Mail = belastbarer Personenkanal → stark genug für PREMIUM.
        pass
    elif k["hat_telefon"] and k["hat_echten_ap"]:
        # Echter, benannter Ansprechpartner + Telefon = belastbar (Call-First).
        pass
    else:
        # Nur Rollen-/Sammel-Mail bzw. Telefon ohne echten Ansprechpartner
        # (oder Artefakt-/Abteilungs-„Name") → kein belastbarer Personenkontakt.
        if k["name_artefakt"]:
            premium_miss.append("Ansprechpartner ist kein echter Name (Abteilung/Artefakt) — kein belastbarer Personenkontakt")
        elif not k["hat_telefon"]:
            premium_miss.append("nur Rollen-/Sammel-Mail, kein Telefon — Kontakt nicht belastbar genug")
        else:
            premium_miss.append("nur Rollen-/Sammel-Mail + Telefon, kein echter Ansprechpartner — nicht send-fertig (Call-First)")
        abzug += 15

    # Regel 2 — Frische des Belegs.
    tage = lead.get("signal_alter_tage")
    datum_unbekannt = not isinstance(tage, int)
    if isinstance(tage, int) and tage > _FRISCH_MAX_TAGE:
        premium_miss.append(f"Beleg veraltet ({tage} Tage > {_FRISCH_MAX_TAGE}) — Stelle evtl. besetzt")
        abzug += 15

    # Regel 7 — echter ICP-Fit.
    fit, fit_grund = _icp_fit(lead, zielbranche)
    if icp_breit:
        # Breiter ICP (z. B. „Versicherungsleads"): das Kaufsignal/der Trigger ist
        # der Qualifizierer, nicht eine enge Branche. Eine Branchen-Abweichung
        # („fail") oder ein nicht prüfbarer ICP („unbestimmt") darf den Lead NICHT
        # rejecten oder PREMIUM blocken — sonst kippt das Gate bei breitem ICP alles.
        # Nur ein echter Branchen-Treffer zählt weiter unten als Plus. Die harten
        # Regeln 1–6 (Website, Kontakt, Frische, Beleg, Engine-Urteil, No-Sales-
        # Postfach) bleiben voll in Kraft — der Qualitäts-Boden bleibt also bestehen.
        pass
    elif fit == "fail":
        kills.append(fit_grund)
        abzug += 25
    elif fit == "unbestimmt":
        premium_miss.append(fit_grund)
        abzug += 10

    # ── Klassen-Entscheid ────────────────────────────────────────────────
    if kills:
        klasse = REJECT
        stufe_cap = NIEDRIG
        gruende = kills + premium_miss
    elif premium_miss:
        klasse = REVIEW
        stufe_cap = MITTEL
        gruende = premium_miss
    else:
        klasse = PREMIUM
        # Nur PREMIUM darf „hoch" — und auch nur bei bekanntem, frischem Datum.
        stufe_cap = MITTEL if datum_unbekannt else HOCH
        pos = []
        if k["ist_mobil"]:
            pos.append("Mobilnummer (Direktkontakt)")
        elif k["hat_telefon"]:
            pos.append("Telefon vorhanden")
        if k["persoenliche_mail"]:
            pos.append("persönliche E-Mail")
        if not datum_unbekannt and isinstance(tage, int):
            pos.append(f"Beleg frisch ({tage} Tage)")
        if fit == "ok":
            pos.append("ICP-Branche passt")
        gruende = ["Premium: " + ", ".join(pos)] if pos else ["Premium: alle harten Regeln erfüllt"]

    return {
        "klasse": klasse,
        "gruende": gruende[:6],
        "abzug": abzug,
        "stufe_cap": stufe_cap,
        "kills": kills,
        "premium_miss": premium_miss,
    }


def anreichern(leads: list[dict], *, zielbranche: str = "", icp_breit: bool = False) -> dict:
    """Heftet je Lead das Gate-Urteil an (in-place) und deckelt die Kaufbereitschaft.

    • ``premium_klasse`` / ``premium_gruende`` / ``premium_abzug`` werden gesetzt.
    • Die vorhandene ``kaufbereitschaft_stufe`` wird auf ``stufe_cap`` gedeckelt —
      so darf **nur** ein PREMIUM-Lead noch „hoch" tragen (Kern-Fix gegen 33/39=hoch).

    Gibt eine Zählung ``{PREMIUM, REVIEW, REJECT}`` zurück.
    """
    zaehlung = {PREMIUM: 0, REVIEW: 0, REJECT: 0}
    _rang = {HOCH: 3, MITTEL: 2, NIEDRIG: 1}
    for lead in leads or []:
        try:
            r = bewerten_premium(lead, zielbranche=zielbranche, icp_breit=icp_breit)
        except Exception:
            r = {"klasse": REVIEW, "gruende": [], "abzug": 50, "stufe_cap": MITTEL}
        lead["premium_klasse"] = r["klasse"]
        lead["premium_gruende"] = r["gruende"]
        lead["premium_abzug"] = r["abzug"]
        lead["premium_stufe_cap"] = r["stufe_cap"]
        # Stufe deckeln (nie hochstufen — nur begrenzen).
        ist = _norm(lead.get("kaufbereitschaft_stufe")).lower() or NIEDRIG
        cap = r["stufe_cap"]
        if _rang.get(ist, 1) > _rang.get(cap, 2):
            lead["kaufbereitschaft_stufe"] = cap
        zaehlung[r["klasse"]] = zaehlung.get(r["klasse"], 0) + 1
    return zaehlung
