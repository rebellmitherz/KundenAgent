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


def parse_phone_de(text: str) -> str:
    """Erste plausible deutsche Telefonnummer aus Freitext; '' wenn keine.

    Konservativ, um Falschtreffer (USt-ID, HRB-Nummer, PLZ, Jahreszahl) zu
    vermeiden: der Kandidat muss mit '+'/'00'/'0' beginnen und 9–15 Ziffern haben.
    """
    if not text:
        return ""
    for m in _PHONE_RE.finditer(text):
        cand = m.group(1).strip()
        digits = re.sub(r"\D", "", cand)
        startet_wie_tel = cand.startswith("+") or cand.startswith("00") or digits.startswith("0")
        if startet_wie_tel and 9 <= len(digits) <= 15:
            return normalize_phone_de(cand)
    return ""


def _name_tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^a-zA-ZäöüÄÖÜß]+", (name or "").lower()) if len(t) >= 2]


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


def _ein_lead(lead: dict, stats: dict, telefon_sucher) -> None:
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
    if _ist_generisch(lead.get("email", "")):
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


def anreichern(leads: list[dict], *, telefon_sucher=None) -> dict:
    """Reichert eine Lead-Liste in-place an. Defensiv: ein einzelner Fehler darf
    den Lauf nie kippen. Gibt eine kleine Statistik zurück.

    ``telefon_sucher``: optionaler Callable ``lead -> text`` für eine echte
    Live-Telefonsuche. Default ``None`` = nur gratis Text-Parse (kein Limit-Verbrauch).
    """
    stats = {"telefon_aus_text": 0, "telefon_live": 0, "mail_vorschlag": 0}
    for lead in leads or []:
        try:
            _ein_lead(lead, stats, telefon_sucher)
        except Exception:
            continue
    return stats
