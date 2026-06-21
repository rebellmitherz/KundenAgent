"""Signal-Discovery — signalbasierte Firmen-Findung für den Auftrag.

Warum diese Schicht existiert
------------------------------
Die normale Suche (`mine.py -i Branche -c Stadt`) findet die Branche *flach* ab —
egal ob eine Firma gerade Bedarf hat. Diese Schicht dreht das um: Sie sucht
zuerst nach einem **Kaufsignal** (z. B. „Firma stellt aktiv Vertrieb ein") und
liefert nur Firmen, die dieses Signal zeigen. Das ist High-Intent-Targeting
statt Gießkanne.

Architektur-Entscheidung (siehe CODE_AGENT_HANDOFF Phase-0-Befund)
------------------------------------------------------------------
Die fertige `run_intent_*`-Kette der Engine ist ein fragmentierter Prototyp
(Marketing-Hardcodes, `-Stadt`-Negation, Preview-Stub beim Firma→Domain-Glied,
nicht-passende Stufen-Verträge). Statt sie wiederzubeleben, nutzt diese Schicht
nur die **funktionierenden, puren** Engine-Bausteine und übergibt die gefundenen
Firmen an die **bewährte** `mine.py --mode enrich`-Pipeline:

  1. Discovery (broad-Modus)   → Firmenname + Signaltitel + Quelle-URL
  2. Website-Auflösung         → offizielle Domain je Firma
  3. CSV → mine.py enrich      → scrape + score + contact_quality + intent

`b2bbot/` wird NICHT verändert — nur importiert/als Subprozess aufgerufen.
Eigenes Fit-Scoring im Produkt-Layer umgeht die Branche/Stadt-Hardcodes der
Engine (`target_preview._INDUSTRY_TERMS` = Marketing/München).

Limits
------
Reiner Aufbau/Test läuft gegen einen gecachten Discovery-Report (kein SERPER).
Live verbraucht: ~6 Discovery-Queries + 1 Website-Query je Firma. `enrich`
scrapt nur (kein Places, kein Versand).
"""
from __future__ import annotations

import csv
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ─── Engine-Zugriff (b2bbot read-only) ───────────────────────────────────────

@contextmanager
def _engine_context(engine_dir: Path):
    """Macht b2bbot-Module importierbar + lädt .env (nur für den Block).

    Verändert b2bbot nicht. sys.path-Eintrag wird nach dem Block entfernt;
    das Arbeitsverzeichnis wird gewechselt (einige Engine-Module lösen
    Output-Pfade relativ auf) und sauber zurückgesetzt.
    """
    engine_dir = Path(engine_dir).resolve()
    added = False
    prev_cwd = Path.cwd()
    if str(engine_dir) not in sys.path:
        sys.path.insert(0, str(engine_dir))
        added = True
    try:
        try:
            from dotenv import load_dotenv  # type: ignore
            load_dotenv(engine_dir / ".env")
        except Exception:
            pass
        os.chdir(engine_dir)
        yield
    finally:
        os.chdir(prev_cwd)
        if added:
            try:
                sys.path.remove(str(engine_dir))
            except ValueError:
                pass


# ─── Datenmodell ─────────────────────────────────────────────────────────────

@dataclass
class SignalFirma:
    firma: str
    signal_titel: str = ""           # z. B. der Stellentitel, der das Signal trägt
    quelle_url: str = ""             # die Job-/Signal-Seite
    fit_score: float = 0.0
    fit_status: str = ""             # target_fit | maybe_fit | weak_fit | discard
    website: str = ""                # nach der Auflösung gesetzt
    website_confidence: float = 0.0

    def als_dict(self) -> dict:
        return {
            "firma": self.firma,
            "signal_titel": self.signal_titel,
            "quelle_url": self.quelle_url,
            "fit_score": self.fit_score,
            "fit_status": self.fit_status,
            "website": self.website,
            "website_confidence": self.website_confidence,
        }


# ─── Produkt-Layer Fit-Scoring (umgeht Engine-Hardcodes) ─────────────────────

_SIGNAL_BEGRIFFE = {
    "sales_hiring": [
        "sales", "vertrieb", "business development", "account manager",
        "neukundenakquise", "sdr", "bdr", "außendienst", "aussendienst",
        "new business",
    ],
    "growth_expansion": [
        "wächst", "waechst", "wachstum", "expansion", "verstärkung",
        "verstaerkung", "neue niederlassung", "neuer standort", "skalierung",
    ],
    # NEU (Weg-2-Tiefe): 4 weitere Signaltypen — A3-Befund „nur 2 von 6".
    # Alle über die bestehende Jobportal-Discovery erkennbar (gleiche Pipeline).
    "appointment_setter": [
        "sdr", "bdr", "sales development", "telefonakquise", "terminierung",
        "inside sales", "telesales", "appointment setter", "vertriebsassistenz",
        "telemarketing", "outbound",
    ],
    "marketing_hiring": [
        "marketing", "performance marketing", "online marketing", "growth",
        "lead generation", "leadgenerierung", "demand generation", "seo", "sea",
        "social media", "kampagne",
    ],
    "leadership_hiring": [
        "head of sales", "vertriebsleiter", "sales director", "leiter vertrieb",
        "chief sales", "cso", "geschäftsführer vertrieb", "head of marketing",
        "vertriebsleitung", "sales lead",
    ],
    "new_location": [
        "neuer standort", "neue niederlassung", "niederlassung", "eröffnet",
        "eroeffnet", "expandiert", "expansion", "markteintritt", "standort",
        "neueröffnung", "neueroeffnung",
    ],
}

# Kanonische Signaltypen + UI-Labels (Quelle der Wahrheit; engine_bridge zieht
# die Labels hierher). Reihenfolge = Stärke-/Relevanz-Reihenfolge fürs Produkt.
SIGNAL_TYPES = (
    "sales_hiring", "growth_expansion", "appointment_setter",
    "marketing_hiring", "leadership_hiring", "new_location",
)
SIGNAL_LABELS = {
    "sales_hiring": "Stellt Vertrieb ein",
    "growth_expansion": "Wächst / baut Team aus",
    "appointment_setter": "Sucht Terminierer / SDR (Outbound)",
    "marketing_hiring": "Investiert in Marketing / Leadgen",
    "leadership_hiring": "Holt Vertriebs-/Marketing-Leitung",
    "new_location": "Eröffnet Standort / expandiert",
}


def _tokens(text: str) -> set[str]:
    return {t for t in "".join(c.lower() if c.isalnum() else " " for c in (text or "")).split() if len(t) >= 3}


# ─── Noise-Erkennung (A3-Befund: ATS-Anbieter, Recruiting, Groß-Konzerne) ─────
# Job-/Bewerber-Plattformen erscheinen als „Firma", weil sie die Stellenanzeige
# HOSTEN — sie sind nie der Interessent. Als ganzes Token im Namen → harte
# Verwerfung (genau das Muster, das `softgarden e-recruiting GmbH` zum Müll-Lead
# gemacht hat). Bewusst konservativ: nur eindeutige Plattform-Namen, keine
# Allerweltswörter wie „jobs"/„talent", die echte Firmennamen treffen würden.
_ATS_PLATTFORMEN = {
    "softgarden", "personio", "stepstone", "lever", "greenhouse", "arbeitnow",
    "kununu", "jobware", "recruitee", "workwise", "heyjobs", "jobvector",
    "absolventa", "yourfirm", "kimeta", "jobninja", "smartrecruiters",
    "stellenanzeigen", "jobscout", "meinestadt",
}
# Personaldienstleister/Recruiting: vermitteln Personal, kaufen selbst keinen
# Akquise-Bot → Abschlag (Substring, da meist Teil eines längeren Namens).
_RECRUITING_BEGRIFFE = (
    "e-recruiting", "recruiting", "personalvermittl", "personalberatung",
    "personaldienstleist", "zeitarbeit", "headhunt", "staffing",
)
# Bekannte Groß-Marken (Stichprobe, erweiterbar) → harte Verwerfung. Ein
# kleiner Akquise-Bot ist für sie kein Thema; sie verbrennen nur Limits + CRM-Platz.
_GROSSMARKEN = {
    "ströer", "stroeer", "bertelsmann", "springer", "telekom", "vodafone",
    "bosch", "siemens", "allianz", "daimler", "mercedes", "sap", "bayer",
    "basf", "henkel", "lufthansa", "commerzbank", "zalando", "sixt",
    "continental", "thyssenkrupp", "rewe", "edeka", "lidl", "saturn", "otto",
    # Konsum-/Filialmarken (große, eigene Vertriebsorga — kein KMU-Ziel).
    # Single-Token = exakter Token-Treffer; mit Leerzeichen = Substring-Treffer.
    "swarovski", "ikea", "mediamarkt", "media markt", "douglas", "rossmann",
    "aldi", "kaufland", "deichmann", "tchibo", "obi", "hornbach", "bauhaus",
    "fielmann", "zara", "decathlon", "porsche", "volkswagen", "audi", "rwe",
    "apollo optik", "post ag", " dhl ", " bmw ",
}
# Strukturelle Groß-Konzern-Indizien (fuzzy) → Abschlag statt harter Verwerfung
# (ein „… Deutschland GmbH" oder eine AG kann selten auch Mittelstand sein).
_GROSSKONZERN_STRUKTUR = (
    "deutschland gmbh", " se ", "se & co", " ag ", "ag & co", "holding",
    " group ", "gruppe", "konzern", "international gmbh",
)


def _match_name(raw: str) -> str:
    """Vergleichs-Form des Firmennamens für die Noise-Filter: casefold,
    „Name "-Präfix weg, mit Leerzeichen umrandet (damit Substring-Treffer wie
    „ se " greifen). KEIN Display-Cleaning — das macht die Putz-Schicht (Weg 1/2)."""
    s = " ".join((raw or "").split()).casefold()
    if s.startswith("name "):
        s = s[5:]
    return f" {s} "


def _name_tokens(match_name: str) -> set[str]:
    return {t for t in "".join(c if c.isalnum() else " " for c in match_name).split()}


def _ist_ats_plattform(match_name: str) -> bool:
    return bool(_name_tokens(match_name) & _ATS_PLATTFORMEN)


def _ist_recruiting(match_name: str) -> bool:
    return any(b in match_name for b in _RECRUITING_BEGRIFFE)


def _ist_grossmarke(match_name: str) -> bool:
    toks = _name_tokens(match_name)
    for marke in _GROSSMARKEN:
        if (marke in match_name) if " " in marke else (marke in toks):
            return True
    return False


def _ist_grosskonzern_struktur(match_name: str) -> bool:
    return any(ind in match_name for ind in _GROSSKONZERN_STRUKTUR)


def _fit_bewerten(firma: str, titel: str, industry: str, city: str, signal_type: str) -> tuple[float, str]:
    """Fit gegen die ECHTEN Auftrags-Parameter (nicht die Engine-Hardcodes).

    Branchen-Fit + Stadt-Fit + Signal-Fit, je gewichtet — abzüglich Noise-Abschläge
    für die drei Müll-Muster aus dem A3-Befund:
      - ATS-/Job-Plattform als „Firma" (softgarden …)   → harte Verwerfung
      - bekannte Groß-Marke (Ströer …)                  → harte Verwerfung
      - Personaldienstleister / Konzern-Struktur        → Abschlag
    Deterministisch, ohne Netz — voll testbar gegen die echten Signal-Leads.
    """
    name = _match_name(firma)

    if _ist_ats_plattform(name):
        return 0.0, "discard"
    if _ist_grossmarke(name):
        return 0.0, "discard"

    hay = f"{firma} {titel}".lower()
    ind_tokens = _tokens(industry)
    city_tokens = _tokens(city)
    sig_terms = _SIGNAL_BEGRIFFE.get(signal_type, [])

    # Ohne Stadt (länderweite Suche) fällt das Stadt-Gewicht weg → auf Branche +
    # Signal umverteilen, damit ein starker Treffer trotzdem target_fit erreicht.
    hat_city = bool(city_tokens)
    w_ind = 0.4 if hat_city else 0.55
    w_sig = 0.3 if hat_city else 0.45

    score = 0.0
    if ind_tokens and any(t in hay for t in ind_tokens):
        score += w_ind
    if hat_city and any(t in hay for t in city_tokens):
        score += 0.3
    if any(t in hay for t in sig_terms):
        score += w_sig

    if _ist_recruiting(name):
        score -= 0.3
    if _ist_grosskonzern_struktur(name):
        score -= 0.35

    score = round(max(0.0, min(1.0, score)), 3)

    if score >= 0.7:
        status = "target_fit"
    elif score >= 0.45:
        status = "maybe_fit"
    elif score >= 0.25:
        status = "weak_fit"
    else:
        status = "discard"
    return score, status


# ─── Query-Bau (sales/growth → Engine; neue Signale → Produkt-Layer) ─────────
# b2bbot.build_job_detail_queries kennt nur sales_hiring/growth_expansion und
# wirft sonst ValueError. Damit die Engine read-only bleibt, bauen wir die
# Queries der neuen Signale hier — im Stil der Engine-Vorlagen (Jobportale +
# Karriereseiten, Negativ-Filter gegen Listen-/Suchergebnis-Seiten).
# Job-Portale je Land (DACH). Pro gewähltem Land kommen dessen Portale dazu,
# danach die länderneutralen Vorlagen (Personio/Join/Lever/Greenhouse + freie Suche).
_PORTAL_TEMPLATES_BY_LAND: dict[str, list[str]] = {
    "de": [
        'site:stepstone.de/stellenangebote-- {base} "{kw}"',
        'site:de.indeed.com/viewjob {base} "{kw}"',
        'site:indeed.com/viewjob {base} "{kw}"',
        # Breiteres Portal-Set (Volumen-Hebel). Alle tragen Job-Detail-Marker in
        # der URL (job/stellenangebot/…) → der Engine-Classifier erkennt sie ohne
        # b2bbot-Eingriff. Der Preview-Resolver zieht den ARBEITGEBER aus dem
        # JobPosting-JSON-LD, nicht den Portalnamen — die ATS-Namensfilter greifen
        # nur, falls die Extraktion fehlschlägt. KEIN Xing/LinkedIn: der Resolver
        # überspringt diese Domains hart (_SKIP_DOMAINS) → wären wirkungslos.
        'site:yourfirm.de {base} "{kw}"',
        'site:jobs.meinestadt.de {base} "{kw}"',
        'site:jobware.de {base} "{kw}"',
        'site:monster.de {base} "{kw}"',
    ],
    "at": [
        'site:stepstone.at {base} "{kw}"',
        'site:at.indeed.com/viewjob {base} "{kw}"',
        'site:karriere.at {base} "{kw}"',
    ],
    "ch": [
        'site:jobs.ch {base} "{kw}"',
        'site:ch.indeed.com/viewjob {base} "{kw}"',
        'site:jobscout24.ch {base} "{kw}"',
    ],
}
_GENERIC_TEMPLATES = [
    'site:personio.de {base} "{kw}"',
    'site:join.com {base} "{kw}"',
    'site:jobs.lever.co {base} "{kw}"',
    'site:greenhouse.io {base} "{kw}"',
    '{base} "{kw}" Karriere Bewerbung -"Jobs & Stellenangebote" -"Stellenangebote in" -"Suchergebnisse"',
]
# Rückwärtskompatibel: der bisherige flache DE-Satz.
_PORTAL_TEMPLATES = _PORTAL_TEMPLATES_BY_LAND["de"] + _GENERIC_TEMPLATES

_DACH = ("de", "at", "ch")


def _laender_normalisieren(laender) -> tuple[str, ...]:
    """Saubert die Länder-Auswahl: nur de/at/ch, Default DE, nie leer."""
    if not laender:
        return ("de",)
    out = tuple(dict.fromkeys(
        l for l in (str(x).strip().lower() for x in laender) if l in _DACH
    ))
    return out or ("de",)


def _portal_templates_fuer(laender) -> list[str]:
    """Portal-Vorlagen für die gewählten Länder + länderneutrale, dedupliziert."""
    tmpl: list[str] = []
    for land in _laender_normalisieren(laender):
        tmpl.extend(_PORTAL_TEMPLATES_BY_LAND.get(land, []))
    tmpl.extend(_GENERIC_TEMPLATES)
    return list(dict.fromkeys(tmpl))


# Such-Keywords für sales/growth, wenn der Engine-Builder nicht greift (z. B.
# ohne Stadt oder außerhalb DE) — damit alle Signaltypen länderweit funktionieren.
# WICHTIG: Deutsche Begriffe ZUERST — die äußere Schleife iteriert Keywords, die
# innere Templates. max_queries schneidet ab; die ersten Keywords bestimmen was
# bei Serper landet. Englische Titel ergänzen, aber niemals zuerst.
_SALES_GROWTH_KEYWORDS: dict[str, list[str]] = {
    "sales_hiring": [
        "Vertriebsmitarbeiter", "Vertrieb", "Außendienst",
        "Neukundengewinnung", "Vertriebsbeauftragter",
        "Sales Manager", "Account Executive",
    ],
    "growth_expansion": [
        "Wir stellen ein", "Team-Ausbau", "neue Stellen", "Wir wachsen",
        "expandiert",
    ],
}

# Such-Keywords je NEUEM Signaltyp (treiben die Discovery-Queries).
_SIGNAL_KEYWORDS: dict[str, list[str]] = {
    "appointment_setter": [
        "Terminierung", "Telefonakquise", "Kaltakquise",
        "Terminakquise", "Outbound-Vertrieb",
        "Sales Development Representative", "SDR", "Inside Sales", "Telesales",
    ],
    "marketing_hiring": [
        "Online-Marketing-Manager", "Performance Marketing", "Leadgenerierung",
        "Marketingleiter", "Marketingmanager",
        "Growth Marketing", "Lead Generation", "Demand Generation",
    ],
    "leadership_hiring": [
        "Vertriebsleiter", "Leiter Vertrieb", "Vertriebsleitung",
        "Geschäftsführer Vertrieb",
        "Head of Sales", "Sales Director",
    ],
    "new_location": [
        "neuer Standort", "neue Niederlassung", "Niederlassung eröffnet",
        "expandiert", "für unseren neuen Standort",
    ],
}


def _build_signal_queries(
    industry: str, city: str, signal_type: str, laender=("de",)
) -> list[str]:
    """Discovery-Queries je Signaltyp + Land. Muss INNERHALB des Engine-Kontexts
    laufen (für den b2bbot-Import bei sales_hiring/growth_expansion).

    Stadt ist optional: ohne Stadt wird länderweit gesucht (Portale je Land).
    """
    st = (signal_type or "").strip().lower()
    city = (city or "").strip()
    laender = _laender_normalisieren(laender)

    # Bewährter Engine-Builder NUR für den DE+Stadt-Fall von sales/growth
    # (unverändert — der erprobte Pfad). Sonst Produkt-Layer (Land/ohne Stadt).
    if st in ("sales_hiring", "growth_expansion") and city and laender == ("de",):
        from modules.intent_job_detail_query_builder import build_job_detail_queries
        return build_job_detail_queries(industry, city, st, relevance_focus="broad")

    kws = _SIGNAL_KEYWORDS.get(st) or _SALES_GROWTH_KEYWORDS.get(st)
    if not kws:
        raise ValueError(f"Unbekannter signal_type: {signal_type!r}. Bekannt: {sorted(SIGNAL_TYPES)}")

    industry = (industry or "").strip()
    if not industry:
        raise ValueError("Zielgruppe/Branche darf nicht leer sein.")

    base = " ".join(p for p in [industry, city] if p).strip()
    templates = _portal_templates_fuer(laender)

    out: list[str] = []
    seen: set[str] = set()
    for kw in kws:
        for tmpl in templates:
            q = tmpl.format(base=base, kw=kw).strip()
            key = q.casefold()
            if q and key not in seen:
                seen.add(key)
                out.append(q)
    return out


# ─── Schritt 1: Discovery ────────────────────────────────────────────────────

def _aus_cache_laden(report_path: Path, industry: str, city: str, signal_type: str) -> list[SignalFirma]:
    """Lädt Firmen aus einem vorhandenen target_preview-Report (kein SERPER)."""
    import json
    data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    out: list[SignalFirma] = []
    for r in data.get("results") or []:
        name = str(r.get("company_name") or "").strip()
        if not name or name == "-" or not r.get("company_name_valid", True):
            continue
        titel = str(r.get("title") or "")
        score, status = _fit_bewerten(name, titel, industry, city, signal_type)
        out.append(SignalFirma(
            firma=name, signal_titel=titel, quelle_url=str(r.get("url") or ""),
            fit_score=score, fit_status=status,
        ))
    return out


# Parallelisierung der Preview-Auflösung. Jeder Kandidat = 1 HTTP-Fetch (8s-Socket-
# Timeout im Resolver). Sequenziell skaliert das nicht: 50+ Kandidaten × bis 8s =
# Minuten / Hänger — der reale Grund, warum große Suchen vorher nicht durchliefen.
# Env-tunebar (analog ENRICH_SCRAPE_WALL_S der enrich-Schicht).
def _preview_workers() -> int:
    try:
        return max(1, min(int(os.environ.get("SIGNAL_PREVIEW_WORKERS", "10") or "10"), 24))
    except (TypeError, ValueError):
        return 10


def _preview_wall_s() -> float:
    try:
        return max(5.0, float(os.environ.get("SIGNAL_PREVIEW_WALL_S", "120") or "120"))
    except (TypeError, ValueError):
        return 120.0


# Obergrenze für die Zahl gefetchter Kandidaten — schützt vor Thread-/Bandbreiten-
# Explosion, unabhängig von max_companies. Genug Puffer zum Filtern.
_CANDIDATE_FETCH_CAP = 60


def _resolve_candidates(candidates: list[dict], resolver, *, max_workers: int = 10,
                        wall_budget_s: float = 120.0) -> list[tuple[dict, dict]]:
    """Löst Job-Detail-Previews PARALLEL auf und gibt (kandidat, resolved)-Paare
    zurück — in Eingabereihenfolge, nur die innerhalb des Budgets fertig gewordenen.

    `resolver` ist injizierbar (Engine-`resolve_portal_job_detail_preview` im Live-
    Pfad, ein Fake im Test) → die Parallel-Logik ist ohne Netz testbar. Fehler je
    Kandidat werden geschluckt (der eine Lead fällt raus, der Lauf lebt weiter);
    was bis zum Wall-Clock-Budget nicht fertig ist, wird verworfen statt zu hängen.
    """
    import concurrent.futures as _cf

    if not candidates:
        return []
    results: list[Optional[dict]] = [None] * len(candidates)
    workers = max(1, min(max_workers, len(candidates)))
    with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
        fut_to_idx = {ex.submit(resolver, c): i for i, c in enumerate(candidates)}
        try:
            for fut in _cf.as_completed(fut_to_idx, timeout=max(1.0, wall_budget_s)):
                idx = fut_to_idx[fut]
                try:
                    results[idx] = fut.result()
                except Exception:
                    results[idx] = None
        except _cf.TimeoutError:
            # Budget erreicht — was fertig ist, nehmen wir; Rest bleibt None.
            pass
    return [(candidates[i], r) for i, r in enumerate(results) if r is not None]


def discover_companies(
    engine_dir: str | Path,
    industry: str,
    city: str,
    signal_type: str = "sales_hiring",
    *,
    max_companies: int = 10,
    provider: str = "serper",
    cached_report: Optional[str | Path] = None,
    max_queries: int = 10,
    max_results_per_query: int = 5,
    laender=("de",),
) -> list[SignalFirma]:
    """Findet Firmen anhand eines Kaufsignals (broad-Modus).

    Wenn ``cached_report`` gesetzt ist, wird der Report wiederverwendet
    (kein SERPER-Call) — fürs Bauen/Testen.
    """
    engine_dir = Path(engine_dir).resolve()
    if cached_report:
        firmen = _aus_cache_laden(Path(cached_report), industry, city, signal_type)
        return [f for f in firmen if f.fit_status != "discard"][:max_companies]

    with _engine_context(engine_dir):
        from modules.intent_search_provider import search_intent_queries
        from modules.intent_portal_url_classifier import classify_portal_url
        from modules.intent_relevance_filter import classify_job_detail_relevance
        from modules.intent_portal_detail_resolver import resolve_portal_job_detail_preview

        # sales_hiring/growth_expansion → bewährter Engine-Builder (broad; der
        # "target_industry"-Pfad ist kaputt). Neue Signale → Produkt-Layer-Queries
        # (die Engine würde sie mit ValueError ablehnen). Siehe _build_signal_queries.
        queries = _build_signal_queries(industry, city, signal_type, laender)[:max_queries]

        batches = search_intent_queries(queries, provider=provider, max_results_per_query=max_results_per_query)
        raw = []
        for b in batches:
            for item in b.get("results") or []:
                raw.append({
                    "query": b.get("query", ""),
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "snippet": str(item.get("snippet") or ""),
                })

        classified = [{**it, **classify_portal_url({"url": it["url"], "title": it["title"], "snippet": it["snippet"]})} for it in raw]
        enriched = classify_job_detail_relevance(classified, industry=industry, city=city)

        # Der Engine-Relevanzfilter ist auf München+Marketing hardcodiert (Legacy):
        # ohne Stadt fällt er auf eine München-Liste zurück und verwirft bei
        # länderweiter Suche ALLES als "wrong_city". Darum greift der Relevanz-
        # Discard nur, wenn eine Stadt gesetzt ist — sonst übernimmt das stadt-
        # tolerante Produkt-Fit-Scoring (_fit_bewerten, weiter unten) das Gaten.
        has_city = bool((city or "").strip())

        # Nur echte Job-Detailseiten, nicht irrelevant; je URL der beste Treffer
        by_url: dict[str, dict] = {}
        for item in enriched:
            if item.get("portal_url_type") != "job_detail_page":
                continue
            if has_city and item.get("relevance_status") == "irrelevant":
                continue
            url = (item.get("url") or "").split("#")[0]
            if not url:
                continue
            cur = float(item.get("relevance_score") or 0)
            if url not in by_url or cur > float(by_url[url].get("relevance_score") or 0):
                by_url[url] = item

        unique = sorted(by_url.values(), key=lambda x: float(x.get("relevance_score") or 0), reverse=True)
        unique = unique[: min(max(max_companies * 2, 8), _CANDIDATE_FETCH_CAP)]

        # Previews PARALLEL auflösen (bounded Worker + Wall-Clock-Budget) statt
        # sequenziell — sonst reißt schon ein Dutzend toter Seiten die Suche in
        # einen mehrminütigen Hänger.
        firmen: list[SignalFirma] = []
        for cand, resolved in _resolve_candidates(
            unique, resolve_portal_job_detail_preview,
            max_workers=_preview_workers(), wall_budget_s=_preview_wall_s(),
        ):
            name = str(resolved.get("company_name_extracted") or "").strip()
            if not resolved.get("company_name_valid") or not name:
                continue
            titel = str(resolved.get("original_title") or cand.get("title") or "")
            score, status = _fit_bewerten(name, titel, industry, city, signal_type)
            if status == "discard":
                continue
            firmen.append(SignalFirma(
                firma=name, signal_titel=titel,
                quelle_url=str(resolved.get("original_url") or cand.get("url") or ""),
                fit_score=score, fit_status=status,
            ))

    # nach Fit sortieren, dedupe nach Firmenname
    firmen.sort(key=lambda f: f.fit_score, reverse=True)
    seen: set[str] = set()
    out: list[SignalFirma] = []
    for f in firmen:
        key = f.firma.casefold().strip()
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out[:max_companies]


# ─── Schritt 2: Website-Auflösung (Firma → offizielle Domain) ────────────────

def resolve_website(
    engine_dir: str | Path,
    company_name: str,
    city: str = "",
    *,
    provider: str = "serper",
) -> tuple[str, float]:
    """Sucht die offizielle Website einer Firma. Gibt (url, confidence) zurück.

    Nutzt die puren Engine-Funktionen `_score_candidate`/`_company_tokens`
    (blocken stepstone/linkedin/xing etc., matchen Markentoken in der Domain).
    Genau 1 SERPER-Query je Firma.
    """
    engine_dir = Path(engine_dir).resolve()
    with _engine_context(engine_dir):
        from modules.intent_search_provider import search_intent_queries
        from modules.intent_company_website_search import _score_candidate

        query = " ".join(p for p in [company_name, city] if p).strip()
        if not query:
            return "", 0.0
        batches = search_intent_queries([query], provider=provider, max_results_per_query=4)
        best_url, best_conf = "", 0.0
        for b in batches:
            for hit in b.get("results") or []:
                scored = _score_candidate(
                    company_name,
                    str(hit.get("title") or ""),
                    str(hit.get("url") or ""),
                    str(hit.get("snippet") or ""),
                )
                if scored.get("is_official_candidate") and float(scored.get("domain_confidence") or 0) > best_conf:
                    best_url = str(hit.get("url") or "")
                    best_conf = float(scored.get("domain_confidence") or 0)
        return best_url, round(best_conf, 3)


def discover_with_websites(
    engine_dir: str | Path,
    industry: str,
    city: str,
    signal_type: str = "sales_hiring",
    *,
    max_companies: int = 10,
    provider: str = "serper",
    cached_report: Optional[str | Path] = None,
    laender=("de",),
    max_queries: int = 10,
    max_results_per_query: int = 5,
) -> list[SignalFirma]:
    """Discovery + Website-Auflösung in einem Schritt."""
    firmen = discover_companies(
        engine_dir, industry, city, signal_type,
        max_companies=max_companies, provider=provider, cached_report=cached_report,
        laender=laender,
        max_queries=max_queries, max_results_per_query=max_results_per_query,
    )
    for f in firmen:
        url, conf = resolve_website(engine_dir, f.firma, city, provider=provider)
        f.website = url
        f.website_confidence = conf
    return firmen


# ─── Schritt 3: CSV für mine.py --mode enrich ────────────────────────────────

_CSV_FIELDS = ["company_name", "website", "city", "industry", "notes"]


def build_enrich_csv(firmen: list[SignalFirma], csv_path: str | Path, *, industry: str = "", city: str = "") -> int:
    """Schreibt die gefundenen Firmen als Enrich-CSV. Gibt Zeilenzahl zurück.

    Nur Firmen MIT aufgelöster Website (sonst kann `enrich` nicht scrapen →
    Minimal-Lead). Signal-Kontext landet in `notes` → fließt als Beschreibung
    in die Intent-Bewertung der Engine ein.
    """
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        w.writeheader()
        for f in firmen:
            if not f.website:
                continue
            notes = f.signal_titel
            if f.quelle_url:
                notes = f"{notes} | Signal-Quelle: {f.quelle_url}".strip(" |")
            w.writerow({
                "company_name": f.firma,
                "website": f.website,
                "city": city,
                "industry": industry,
                "notes": notes,
            })
            n += 1
    return n


# ─── Standalone-Test (gegen Cache, minimale Limits) ──────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    here = Path(__file__).resolve()
    default_engine = here.parents[2] / "b2bbot"

    ap = argparse.ArgumentParser(description="Signal-Discovery Standalone-Test")
    ap.add_argument("--engine-dir", default=str(default_engine))
    ap.add_argument("--industry", default="Unternehmensberatung")
    ap.add_argument("--city", default="Hamburg")
    ap.add_argument("--signal", default="sales_hiring")
    ap.add_argument("--max", type=int, default=5)
    ap.add_argument("--cached-report", default="", help="target_preview-Report wiederverwenden (kein SERPER für Discovery)")
    ap.add_argument("--no-website", action="store_true", help="Website-Auflösung überspringen (0 SERPER-Calls)")
    ap.add_argument("--csv-out", default="")
    args = ap.parse_args()

    cached = args.cached_report or None
    firmen = discover_companies(
        args.engine_dir, args.industry, args.city, args.signal,
        max_companies=args.max, cached_report=cached,
    )
    print(f"== Discovery: {len(firmen)} Firmen ({args.industry} / {args.city} / {args.signal}) ==")
    for f in firmen:
        print(f"  - {f.firma} | fit={f.fit_score} ({f.fit_status}) | {f.signal_titel[:60]}")

    if not args.no_website:
        for f in firmen:
            url, conf = resolve_website(args.engine_dir, f.firma, args.city)
            f.website, f.website_confidence = url, conf
            print(f"    → website: {url or '-'} (conf {conf})")

    if args.csv_out:
        n = build_enrich_csv(firmen, args.csv_out, industry=args.industry, city=args.city)
        print(f"== CSV geschrieben: {n} Zeilen → {args.csv_out}")
