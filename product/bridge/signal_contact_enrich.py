"""Kontakt-Anreicherung für Signal-Leads (Weg-2-Tiefe).

A3-Befund: Der Signal-Pfad liefert dünnere Kontaktdaten als der Branchen-/
Places-Pfad — oft fehlt das Telefon (z. B. Medialabel) und es bleibt nur eine
generische ``info@``-Mail. Diese Schicht reichert NACH dem enrich an, ohne die
Engine zu verändern und ohne Auto-Send:

  1. **Telefon** — wenn keins erkannt wurde, parsen wir zuerst die von der Engine
     **bereits gescrapten** Textfelder (Impressum/Geo-Evidence). Das kostet KEINE
     zusätzliche Suchabfrage und holt Nummern zurück, die die enge Telefon-Regex
     der Engine übersehen hat. Optional (opt-in, AUS per Default) kann ein
     injizierter ``telefon_sucher`` eine echte Live-Suche/Scrape anstoßen.
  2. **Persönliche Mail** — KEINE Erfindung. Wir wählen nur den besten bereits
     von der Engine erzeugten ``email_pattern_suggestions``-Eintrag passend zum
     Entscheidernamen und legen ihn als klar gekennzeichneten **Vorschlag** ab
     (``persoenliche_mail_vorschlag``) — NICHT in ``email``, kein Auto-Send.

Leitplanken: Engine read-only · kein Auto-Send · keine Fake-Personalisierung.
Alles deterministisch + testbar; der einzige Live-Teil ist der optionale
``telefon_sucher`` (Provider-Injektion).
"""
from __future__ import annotations

import re

# Von der Engine beim enrich bereits gescrapte Textfelder — hier steht die
# Telefonnummer oft im Klartext, auch wenn `phone` leer blieb.
_TEXT_FELDER = (
    "impressum_info", "geo_site_evidence_text", "geo_evidence_text",
    "description", "search_snippet",
)

# Telefon-Kandidat in Freitext: beginnt mit + oder Ziffer, dann Trenner erlaubt.
_PHONE_RE = re.compile(r"(?<![\w])(\+?\d[\d\s()/\-]{6,}\d)")


def normalize_phone_de(raw: str) -> str:
    """Leichte Normierung: Trenner raus, 00→+. Liefert eindeutige Ziffernfolge
    (kein strenges E.164 — die Engine hat dafür ihr eigenes phone_clean)."""
    s = (raw or "").strip()
    if not s:
        return ""
    plus = s.startswith("+") or s.startswith("00")
    digits = re.sub(r"\D", "", s)
    if s.startswith("00"):
        digits = digits[2:]
    return ("+" + digits) if (plus and digits) else digits


def ist_plausible_telefonnummer(raw: str) -> bool:
    """False bei offensichtlich unsinnigen Nummern (Platzhalter/Parse-Artefakt).

    Fängt z. B. ``+4900000001728`` (langer Nullen-Lauf, real gesehen) oder
    ``1111111111``. Konservativ — echte Nummern haben nie 5 gleiche Ziffern
    am Stück und mehr als zwei verschiedene Ziffern.
    """
    d = re.sub(r"\D", "", raw or "")
    if not (9 <= len(d) <= 15):
        return False
    if re.search(r"(\d)\1{4,}", d):          # >=5 gleiche Ziffern am Stück
        return False
    if len(set(d)) <= 2:                      # nur 1–2 verschiedene Ziffern
        return False
    return True


def parse_phone_de(text: str) -> str:
    """Erste plausible deutsche Telefonnummer aus Freitext; '' wenn keine.

    Konservativ, um Falschtreffer (USt-ID, HRB-Nummer, PLZ, Jahreszahl) zu
    vermeiden: der Kandidat muss mit '+'/'00'/'0' beginnen, 9–15 Ziffern haben
    und ``ist_plausible_telefonnummer`` bestehen (keine 0000-Platzhalter).
    """
    if not text:
        return ""
    for m in _PHONE_RE.finditer(text):
        cand = m.group(1).strip()
        digits = re.sub(r"\D", "", cand)
        startet_wie_tel = cand.startswith("+") or cand.startswith("00") or digits.startswith("0")
        if startet_wie_tel and 9 <= len(digits) <= 15 and ist_plausible_telefonnummer(digits):
            return normalize_phone_de(cand)
    return ""


def _name_tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^a-zA-ZäöüÄÖÜß]+", (name or "").lower()) if len(t) >= 2]


# ─── Müll-Namen-Filter ──────────────────────────────────────────────────────
# Der Scraper greift manchmal Tech-Erwähnungen oder Rechtstexte als Personenname
# ab (z. B. "Adobe Fonts", "Google Inc"). Diese werden vor der Anreicherung
# geleert — lieber kein Name als ein falscher.

_MULL_NAME_EXAKT = frozenset({
    "adobe fonts", "google inc", "google llc", "google analytics",
    "google maps", "google tag manager", "microsoft corporation",
    "microsoft corp", "cloudflare inc", "cloudflare", "jquery foundation",
    "font awesome", "bootstrap", "wordpress", "webmaster",
    "administrator", "redaktion",
})

_MULL_NAME_TOKENS = frozenset({
    "adobe", "google", "microsoft", "cloudflare", "jquery",
    "wordpress", "github", "instagram", "facebook", "analytics",
    "fonts", "copyright",
})

_MULL_DIGIT_RE = re.compile(r"\d")
_MULL_RECHT_RE = re.compile(r"[§©®™]|gmbh\s*&|e\.?\s*v\.?\b", re.I)

# Token, die in einem PERSONEN-Namen nie vorkommen — verirrte Rechtsform-/
# Platzhalter-Fragmente, die der Scraper als „Name" abgreift („… Inc", „Firmenname B2B").
_MULL_NAME_HART_TOKENS = frozenset({"inc", "b2b", "firmenname", "musterfirma"})

# Funktions-/Abteilungs-/Scrape-Artefakt-Wörter: kein echter Ansprechpartner,
# sondern eine Stelle/Region/Überschrift, die der Scraper als „Name" abgreift
# (z. B. „Regionaldirektion Bayern", „Angaben May und Olde", „Zentrale"). Diese
# Wörter kommen in einem echten Personennamen nie vor → konservativ.
_MULL_NAME_FUNKTION = frozenset({
    "regionaldirektion", "direktion", "niederlassung", "filiale", "geschaeftsstelle",
    "geschäftsstelle", "vertretung", "zentrale", "abteilung", "sekretariat",
    "empfang", "buchhaltung", "personalabteilung", "kundenservice", "kundendienst",
    "service", "support", "vertrieb", "verwaltung", "team", "angaben", "impressum",
    "kontakt", "ansprechpartner", "geschaeftsfuehrung", "geschäftsführung",
})

# Akademische Titel-/Grad-Fragmente. Stehen sie OHNE echten Vor-+Nachnamen dahinter
# (z. B. „Parmentier Dipl"), ist der „Name" nur ein Titelrest = Artefakt.
_NAME_TITEL = frozenset({"dipl", "ing", "dr", "prof", "mba", "msc", "bsc", "llm", "phd", "med"})

# ─── Firmenname-/Domain-Artefakte (Schritt-3-Erweiterung) ───────────────────
# Harte Platzhalter: tauchen sie im Firmennamen auf, ist es kein echter Betrieb.
_FIRMA_HART_PLATZHALTER = frozenset({
    "firmenname", "musterfirma", "mustermann", "musterfrau", "beispielfirma",
    "amercia", "yourcompany", "yourdomain", "testfirma", "deinefirma", "ihrefirma",
})
# Rechtsform-Suffixe — beim Inhalts-Check ignoriert (sonst zählt „GmbH" als Inhalt).
_FIRMA_SUFFIXE = frozenset({
    "inc", "gmbh", "ag", "kg", "ohg", "ug", "mbh", "co", "ltd", "llc", "kgaa",
    "se", "ev", "eg", "gbr", "und", "the",
})
# Junk-Inhalts-Token: besteht ein Firmenname NUR daraus, ist er ein Platzhalter
# („B2B", „Firmenname B2B", „Test"). Ein echter Name hat mindestens ein anderes Wort.
_FIRMA_JUNK = _FIRMA_HART_PLATZHALTER | frozenset({
    "b2b", "test", "muster", "beispiel", "example", "demo", "platzhalter",
})

# Platzhalter-/Demo-Domains — eine Website, die so aussieht, ist keine echte Firma.
_PLATZHALTER_DOMAIN_TOKENS = (
    "yourdomain", "example.", "example-", "musterfirma", "mustermann", "musterfrau",
    "beispiel", "company.com", "firmenname", "test.de", "domain.de", "ihre-domain",
    "ihredomain", "deine-domain", "platzhalter",
)


def _ist_mull_name(name: str) -> bool:
    """True wenn `name` offensichtlich kein Personenname ist.

    Konservativ: lieber einen echten Namen behalten als fälschlich entfernen.
    Prüft: bekannte Tech-/Firmennamen, Rechtstextfragmente, Ziffern, Überlänge,
    verirrte Rechtsform-/Platzhalter-Token und alleinstehende akademische Titel.
    """
    if not name:
        return False
    n = name.strip()
    if not n:
        return False
    nl = n.lower()
    if nl in _MULL_NAME_EXAKT:
        return True
    if len(n) > 50:        # echte GF-Namen sind kürzer
        return True
    if _MULL_DIGIT_RE.search(n):
        return True
    if _MULL_RECHT_RE.search(n):
        return True
    woerter = [w for w in re.split(r"[^a-zA-ZäöüÄÖÜß]+", nl) if w]
    wortmenge = set(woerter)
    if wortmenge & _MULL_NAME_TOKENS:
        return True
    if wortmenge & _MULL_NAME_HART_TOKENS:        # „… Inc" / „Firmenname B2B"
        return True
    if wortmenge & _MULL_NAME_FUNKTION:           # „Regionaldirektion Bayern" / „Angaben …"
        return True
    # Titelrest ohne echten Namen (z. B. „Parmentier Dipl"): bleiben nach Abzug der
    # akademischen Titel < 2 echte Namens-Token, ist es ein Artefakt — ein echter
    # Name wie „Dr. Hans Müller" behält Hans + Müller und bleibt erhalten.
    if wortmenge & _NAME_TITEL:
        echt = [w for w in woerter if w not in _NAME_TITEL and len(w) >= 2]
        if len(echt) < 2:
            return True
    return False


# Firmenstruktur-/Sammelbegriffe, die der Scraper HINTER einen echten Namen hängt
# ("Marius Heinze Niederlassungen", "Harry Ritter Bankinstitut"). Werden als SUFFIX
# abgeschnitten, solange ein echter Vor+Nachname (>=2 Token) stehen bleibt.
_NAME_ARTEFAKT_STAEMME = tuple(sorted(_MULL_NAME_FUNKTION | {
    "bankinstitut", "manufaktur", "cooperation", "kooperation",
    "unternehmensgruppe", "genossenschaft", "holding",
}))


def _ist_artefakt_wort(wort: str) -> bool:
    """True wenn `wort` ein Firmenstruktur-/Sammelbegriff ist (auch Plural)."""
    w = re.sub(r"[^a-zäöüß]", "", (wort or "").lower())
    if not w:
        return False
    return any(
        w in (stamm, stamm + "en", stamm + "e", stamm + "s")
        for stamm in _NAME_ARTEFAKT_STAEMME
    )


def _kuerze_namen_artefakt(name: str) -> str:
    """Schneidet Firmenstruktur-/Sammelbegriffe am ENDE eines Namens ab, solange
    ein echter Vor+Nachname (>=2 Token) übrig bleibt. Konservativ: nur am Wortende.

    "Marius Heinze Niederlassungen" -> "Marius Heinze". Kein Artefakt -> unverändert.
    (Bleibt danach nur Struktur-Müll übrig, fängt ihn `_ist_mull_name`.)
    """
    if not name:
        return name
    teile = name.split()
    while len(teile) > 2 and _ist_artefakt_wort(teile[-1]):
        teile = teile[:-1]
    return " ".join(teile)


def _firma_tokens(name: str) -> set[str]:
    # Ziffern BLEIBEN im Token (sonst zerfällt „B2B"→„b" und „3M"→„m") — so bleibt
    # „B2B" als Junk erkennbar und „3M Deutschland" als echte Firma erhalten.
    return {w for w in re.split(r"[^a-z0-9äöüß]+", (name or "").lower()) if w}


def _ist_mull_firma(name: str) -> bool:
    """True wenn `name` kein echter Firmenname ist (Platzhalter/Artefakt).

    Konservativ — ein echter Betrieb mit Ziffer (z. B. „3M Deutschland") oder
    Rechtsform bleibt erhalten. Greift nur bei harten Platzhaltern oder wenn der
    Name AUSSCHLIESSLICH aus Junk-Token besteht (z. B. „B2B", „Firmenname B2B").
    """
    toks = _firma_tokens(name)
    if not toks:
        return False
    if toks & _FIRMA_HART_PLATZHALTER:
        return True
    inhalt = toks - _FIRMA_SUFFIXE          # echte Inhalts-Token ohne Rechtsform
    if inhalt and inhalt <= _FIRMA_JUNK:
        return True
    return False


def _ist_platzhalter_domain(text: str) -> bool:
    """True wenn die Website/Domain wie ein Demo-/Platzhalter aussieht."""
    u = (text or "").strip().lower()
    return bool(u) and any(tok in u for tok in _PLATZHALTER_DOMAIN_TOKENS)


# ─── Rollen-/Sammel-Postfächer ──────────────────────────────────────────────
# Rollen-/Sammel-Postfächer — NIE als „persönlicher" Vorschlag (das wäre Fake-
# Personalisierung) und der Trigger dafür, dass eine Mail als generisch gilt.
_ROLE_LOCALS = {
    "info", "kontakt", "contact", "office", "mail", "hello", "hallo", "service",
    "team", "willkommen", "moin", "post", "webseiten", "webseite", "web",
    "newsletter", "presse", "marketing", "vertrieb", "sales", "support", "jobs",
    "karriere", "bewerbung", "datenschutz", "noreply", "no-reply", "admin",
    "mailbox", "empfang", "anfrage", "buchhaltung",
}


def _local(email: str) -> str:
    return (email or "").split("@", 1)[0].lower().strip()


def _domain(url: str) -> str:
    """Bloße Domain aus einer Website-URL ('https://www.Firma.de/x' → 'firma.de')."""
    u = (url or "").strip().lower()
    if not u:
        return ""
    u = re.sub(r"^https?://", "", u).split("/", 1)[0]
    return u[4:] if u.startswith("www.") else u


def best_personal_email(lead: dict) -> str:
    """Bester persönlicher Mail-VORSCHLAG aus den Engine-Pattern-Vorschlägen,
    passend zum Entscheidernamen. KEINE Erfindung — nur Auswahl, und NUR echte
    Namens-Treffer (Rollen-Adressen wie webseiten@/info@ sind keine Person).
    '' wenn kein Name bekannt ist oder nichts passt — lieber nichts als Fake."""
    suggestions = [
        s.strip() for s in (lead.get("email_pattern_suggestions") or [])
        if isinstance(s, str) and "@" in s and _local(s) not in _ROLE_LOCALS
    ]
    name = (
        lead.get("contact_full_name") or lead.get("managing_director")
        or lead.get("contact_person") or ""
    )
    toks = _name_tokens(name)
    if not suggestions or not toks:
        return ""
    vor, nach = toks[0], toks[-1]
    for s in suggestions:                            # 1. Wahl: vorname.nachname@
        if _local(s) == f"{vor}.{nach}":
            return s
    if vor != nach:                                  # 2. Wahl: beide Namensteile drin
        for s in suggestions:
            if vor in _local(s) and nach in _local(s):
                return s
    for s in suggestions:                            # 3. Wahl: exakt Vor- oder Nachname
        if _local(s) in (vor, nach):
            return s
    return ""                                        # kein Namens-Treffer → kein Vorschlag


def _ist_generisch(email: str) -> bool:
    return (not email) or _local(email) in _ROLE_LOCALS


def _ein_lead(lead: dict, stats: dict, telefon_sucher, person_sucher=None) -> None:
    # 0) Namen säubern: (a) Firmenstruktur-Suffix abschneiden ("Marius Heinze
    #    Niederlassungen" -> "Marius Heinze"), (b) bleibt Müll (Tech-Marke,
    #    Rechtstext, reiner Struktur-Begriff) -> leeren. Leer ist besser als falsch.
    for feld in ("managing_director", "contact_person", "contact_full_name"):
        val = (lead.get(feld) or "").strip()
        if not val:
            continue
        gekuerzt = _kuerze_namen_artefakt(val)
        if gekuerzt != val:
            val = gekuerzt
            lead[feld] = gekuerzt
            stats["namen_artefakt_gekuerzt"] += 1
        if _ist_mull_name(val):
            lead[feld] = ""
            stats["mull_namen_bereinigt"] += 1

    # 0b) Firmenname-/Domain-Artefakt FLAGGEN (nicht löschen — ein Firmenname ist zu
    #     wertvoll zum Leeren). Das Premium-Gate verwertet das Flag für REJECT.
    firma = (lead.get("company_name") or lead.get("company_name_clean") or "").strip()
    if (firma and _ist_mull_firma(firma)) or _ist_platzhalter_domain(lead.get("website") or ""):
        if not lead.get("company_name_artefakt"):
            lead["company_name_artefakt"] = True
            stats["firma_artefakt"] += 1

    # 0c) Vorhandene Telefonnummer plausibilisieren: Platzhalter/Parse-Artefakte
    #     (z. B. "+4900000001728" — langer Nullen-Lauf) leeren, damit die
    #     Anreicherung unten eine echte sucht und das Gate keine Fake-Nummer als
    #     "Telefon vorhanden" wertet.
    vorhandene_tel = (lead.get("phone") or lead.get("phone_clean") or "").strip()
    if vorhandene_tel and not ist_plausible_telefonnummer(vorhandene_tel):
        lead["phone"] = ""
        lead["phone_clean"] = ""
        lead["has_phone"] = False
        stats["telefon_unplausibel_geleert"] += 1

    # 0.5) Entscheider-Anreicherung (OPT-IN, KOSTENPFLICHTIG). Läuft NUR, wenn ein
    #     person_sucher injiziert wurde (= API-Key gesetzt → sonst None = 0 €) UND
    #     der Lead noch KEINEN Namen hat (Gap-Füller, kein Pauschal-Anreichern) UND
    #     eine Domain existiert. Füllt ausschließlich LEERE Felder — überschreibt
    #     nie vorhandene Daten, schließt die LinkedIn-Personen-Lücke (0/14).
    hat_namen = bool(
        (lead.get("managing_director") or lead.get("contact_full_name")
         or lead.get("contact_person") or "").strip()
    )
    if person_sucher and not hat_namen and (lead.get("website") or "").strip():
        try:
            treffer = person_sucher(lead) or {}
        except Exception:
            treffer = {}
        name = (treffer.get("name") or "").strip() if isinstance(treffer, dict) else ""
        if name and not _ist_mull_name(name):
            lead["managing_director"] = lead.get("managing_director") or name
            lead["contact_full_name"] = lead.get("contact_full_name") or name
            lead["kontakt_anreicherung"] = "person_pdl"
            stats["person_angereichert"] += 1
            li = (treffer.get("linkedin_url") or "").strip()
            if li and not (lead.get("linkedin_person_url") or "").strip():
                lead["linkedin_person_url"] = li
            tel = (treffer.get("phone") or "").strip()
            if tel and not (lead.get("phone") or lead.get("phone_clean") or "").strip():
                lead["phone"] = tel
                lead["phone_clean"] = tel
                lead["has_phone"] = True
            mail = (treffer.get("email") or "").strip()
            if mail and "@" in mail and not lead.get("persoenliche_mail_vorschlag"):
                lead["persoenliche_mail_vorschlag"] = mail

    # 1) Telefon — nur wenn keins da. Erst aus bereits gescraptem Text (gratis),
    #    dann optional live (nur wenn ein Sucher injiziert wurde).
    hat_phone = bool((lead.get("phone") or lead.get("phone_clean") or "").strip())
    if not hat_phone:
        gefunden = ""
        for feld in _TEXT_FELDER:
            gefunden = parse_phone_de(str(lead.get(feld) or ""))
            if gefunden:
                stats["telefon_aus_text"] += 1
                lead["kontakt_anreicherung"] = "telefon_aus_text"
                break
        if not gefunden and telefon_sucher and (lead.get("website") or "").strip():
            try:
                gefunden = parse_phone_de(telefon_sucher(lead) or "")
            except Exception:
                gefunden = ""
            if gefunden:
                stats["telefon_live"] += 1
                lead["kontakt_anreicherung"] = "telefon_live"
        if gefunden:
            lead["phone"] = gefunden
            lead["phone_clean"] = gefunden
            lead["has_phone"] = True

    # 2) Persönliche Mail — NUR Vorschlag (nie in `email`, kein Auto-Send), und
    #    nur wenn die bisherige Mail generisch/leer ist (sonst kein Mehrwert).
    #    Ein bereits gesetzter Vorschlag (z. B. echte PDL-Work-Mail) bleibt — eine
    #    verifizierte Adresse schlägt jede Pattern-Vermutung.
    if _ist_generisch(lead.get("email", "")) and not lead.get("persoenliche_mail_vorschlag"):
        vorschlag = best_personal_email(lead)
        if vorschlag and vorschlag.lower() != (lead.get("email") or "").lower():
            lead["persoenliche_mail_vorschlag"] = vorschlag
            stats["mail_vorschlag"] += 1


def make_serper_telefon_sucher(api_key: str):
    """Fabrik für einen SERPER-basierten Live-Telefon-Sucher (~1 Query/Lead).

    Gibt einen Callable lead→text zurück der die Google-Snippet-Texte zum
    Impressum zurückliefert. Daraus extrahiert parse_phone_de die Nummer.
    Nur aktiv wenn api_key gesetzt (sonst None zurückgeben und Fabrik gar nicht
    aufrufen). Nutzt ausschließlich stdlib — kein requests/httpx.
    """
    import json as _json
    import urllib.request as _req

    def _sucher(lead: dict) -> str:
        firma = (lead.get("company_name") or "").strip()
        if not firma:
            return ""
        try:
            query = f'"{firma}" impressum telefon'
            payload = _json.dumps({"q": query, "num": 3}).encode()
            request = _req.Request(
                "https://google.serper.dev/search",
                data=payload,
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            )
            with _req.urlopen(request, timeout=8) as resp:
                data = _json.loads(resp.read().decode())
            return " ".join(
                (r.get("snippet") or "") + " " + (r.get("title") or "")
                for r in data.get("organic", [])[:3]
            )
        except Exception:
            return ""

    return _sucher


def make_pdl_person_enricher(api_key: str):
    """Fabrik für einen People-Data-Labs-Entscheider-Sucher — OPT-IN, KOSTENPFLICHTIG.

    ⚠️ KOSTET GELD (~$0,01–0,05 je Treffer). Wird NUR erzeugt/aktiv, wenn ein
    ``PDL_API_KEY`` gesetzt ist — ohne Key gibt es diesen Sucher gar nicht (None)
    und es entstehen **0 €**. Gedacht ausschließlich als **Gap-Füller** für Leads,
    bei denen das (gratis) Impressum KEINEN Entscheidernamen lieferte — nicht zum
    Pauschal-Anreichern aller Leads.

    Gibt einen Callable ``lead -> dict`` zurück:
    ``{name, email, phone, linkedin_url, title}`` (leeres dict wenn nichts).
    Sucht über die Firmen-Domain einen Entscheider mit Leitungs-/Vertriebsrolle.
    stdlib-only (urllib) — kein requests/httpx. Die SQL-Query wird beim ersten
    echten Lauf gegen reale PDL-Treffer feinjustiert (Scaffold steht startklar).
    """
    import json as _json
    import urllib.request as _req

    def _sucher(lead: dict) -> dict:
        dom = _domain(lead.get("website") or "")
        if not dom:
            return {}
        try:
            sql = (
                "SELECT * FROM person "
                f"WHERE job_company_website='{dom}' "
                "AND job_title_levels IN ('owner','cxo','vp','director','manager')"
            )
            payload = _json.dumps({"sql": sql, "size": 1}).encode()
            request = _req.Request(
                "https://api.peopledatalabs.com/v5/person/search",
                data=payload,
                headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            )
            with _req.urlopen(request, timeout=10) as resp:
                data = _json.loads(resp.read().decode())
            rec = (data.get("data") or [None])[0]
            if not isinstance(rec, dict):
                return {}
            phones = rec.get("phone_numbers") or []
            return {
                "name": rec.get("full_name") or "",
                "email": rec.get("work_email") or rec.get("recommended_personal_email") or "",
                "phone": (rec.get("mobile_phone") or (phones[0] if phones else "")) or "",
                "linkedin_url": rec.get("linkedin_url") or "",
                "title": rec.get("job_title") or "",
            }
        except Exception:
            return {}

    return _sucher


def anreichern(leads: list[dict], *, telefon_sucher=None, person_sucher=None) -> dict:
    """Reichert eine Lead-Liste in-place an. Defensiv: ein einzelner Fehler darf
    den Lauf nie kippen. Gibt eine kleine Statistik zurück.

    ``telefon_sucher``: optionaler Callable ``lead -> text`` für eine echte
    Live-Telefonsuche. Default ``None`` = nur gratis Text-Parse (kein Limit-Verbrauch).

    ``person_sucher``: optionaler Callable ``lead -> dict`` (z. B. People Data Labs)
    für eine KOSTENPFLICHTIGE Entscheider-Anreicherung. Default ``None`` = AUS = 0 €.
    Läuft nur bei Leads OHNE Namen + mit Domain (Gap-Füller).
    """
    stats = {
        "telefon_aus_text": 0, "telefon_live": 0, "mail_vorschlag": 0,
        "mull_namen_bereinigt": 0, "person_angereichert": 0, "firma_artefakt": 0,
        "namen_artefakt_gekuerzt": 0, "telefon_unplausibel_geleert": 0,
    }
    for lead in leads or []:
        try:
            _ein_lead(lead, stats, telefon_sucher, person_sucher)
        except Exception:
            continue
    return stats
