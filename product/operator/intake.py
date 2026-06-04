"""Operator-Intake — Freitext → Auftrags-Entwurf.

Das Herzstück: aus normaler Sprache des Kunden einen strukturierten Auftrag
machen. Erkennt fehlende Felder und stellt gezielte Rückfragen. Unterstützt
Mehrfach-Dialog (Kunde ergänzt fehlende Angaben nach und nach).

Hybrid-Design:
  - Deterministischer Parser als verlässliche Basis (ohne API-Key, voll testbar).
  - Optionaler LLM-Pfad (llm_fn) für schwierige Formulierungen.

Der Intake erzeugt NUR einen Entwurf (status=ENTWURF). Die Bestätigung ist
ein eigener Schritt (confirm.py) — niemals hier automatisch.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from product.operator.order_schema import Auftrag, Qualitaetskriterien


# llm_fn(system_prompt, user_prompt) -> str  (erwartet JSON-Text als Antwort)
LLMFn = Callable[[str, str], str]


# --- Bekannte Branchen (synonyme → kanonischer Anzeigename) -----------------
# Angelehnt an die 15 Vertical-Profile der Engine (config/industry_profiles.py).
_BRANCHEN_SYNONYME = {
    "handwerker": "Handwerker", "handwerk": "Handwerker",
    "dachdecker": "Dachdecker", "elektriker": "Elektriker",
    "maler": "Maler", "sanitär": "Sanitär", "shk": "Sanitär",
    "agentur": "Agenturen", "agenturen": "Agenturen", "marketingagentur": "Agenturen",
    "it dienstleister": "IT Dienstleister", "it-dienstleister": "IT Dienstleister",
    "it": "IT Dienstleister", "msp": "IT Dienstleister", "systemhaus": "IT Dienstleister",
    "beratung": "Beratungen", "beratungen": "Beratungen", "consultant": "Beratungen",
    "unternehmensberatung": "Beratungen",
    "immobilienmakler": "Immobilienmakler", "makler": "Immobilienmakler",
    "pflege": "Pflegeanbieter", "pflegeanbieter": "Pflegeanbieter", "pflegedienst": "Pflegeanbieter",
    "coach": "Coaches", "coaches": "Coaches", "coaching": "Coaches",
    "steuerberater": "Steuerberater", "steuerkanzlei": "Steuerberater",
    "recruiting": "Recruiting", "personalvermittlung": "Recruiting", "headhunter": "Recruiting",
    "solar": "PV/Solar", "photovoltaik": "PV/Solar", "pv": "PV/Solar", "solarteur": "PV/Solar",
    "sicherheitsdienst": "Sicherheitsdienst", "security": "Sicherheitsdienst",
    "fitnessstudio": "Fitnessstudios", "fitnessstudios": "Fitnessstudios", "gym": "Fitnessstudios",
    "gastronomie": "Gastronomie", "restaurant": "Gastronomie", "gastro": "Gastronomie",
    "arztpraxis": "Arztpraxen", "arztpraxen": "Arztpraxen", "praxis": "Arztpraxen",
    "reinigung": "Reinigung", "reinigungsfirma": "Reinigung", "gebäudereinigung": "Reinigung",
}

# --- Bekannte Regionen (synonyme → kanonischer Anzeigename) -----------------
_REGION_SYNONYME = {
    "nrw": "NRW", "nordrhein-westfalen": "NRW", "nordrhein westfalen": "NRW",
    "bayern": "Bayern", "by": "Bayern",
    "baden-württemberg": "Baden-Württemberg", "bw": "Baden-Württemberg", "bawü": "Baden-Württemberg",
    "hessen": "Hessen", "niedersachsen": "Niedersachsen", "sachsen": "Sachsen",
    "rheinland-pfalz": "Rheinland-Pfalz", "schleswig-holstein": "Schleswig-Holstein",
    "thüringen": "Thüringen", "brandenburg": "Brandenburg", "saarland": "Saarland",
    "mecklenburg-vorpommern": "Mecklenburg-Vorpommern", "sachsen-anhalt": "Sachsen-Anhalt",
    "bremen": "Bremen",
    # Großstädte
    "berlin": "Berlin", "hamburg": "Hamburg", "münchen": "München", "muenchen": "München",
    "köln": "Köln", "koeln": "Köln", "frankfurt": "Frankfurt", "stuttgart": "Stuttgart",
    "düsseldorf": "Düsseldorf", "duesseldorf": "Düsseldorf", "dortmund": "Dortmund",
    "essen": "Essen", "leipzig": "Leipzig", "dresden": "Dresden", "hannover": "Hannover",
    "nürnberg": "Nürnberg", "nuernberg": "Nürnberg", "bremen ": "Bremen",
    "duisburg": "Duisburg", "bochum": "Bochum", "wuppertal": "Wuppertal",
    "bielefeld": "Bielefeld", "bonn": "Bonn", "münster": "Münster", "muenster": "Münster",
    "mannheim": "Mannheim", "karlsruhe": "Karlsruhe", "augsburg": "Augsburg",
}

# --- Angebot-Erkennung (was der Kunde verkauft) -----------------------------
_ANGEBOT_KEYWORDS = {
    "website": "Website", "webseite": "Website", "homepage": "Website",
    "webdesign": "Webdesign", "web-design": "Webdesign",
    "seo": "SEO", "suchmaschinenoptimierung": "SEO",
    "social media": "Social Media", "social-media": "Social Media",
    "marketing": "Marketing", "online-marketing": "Online-Marketing",
    "werbung": "Werbung", "ads": "Ads", "google ads": "Google Ads",
    "shop": "Online-Shop", "onlineshop": "Online-Shop", "e-commerce": "E-Commerce",
    "software": "Software", "app": "App", "automatisierung": "Automatisierung",
    "ki": "KI-Lösung", "ai": "KI-Lösung",
}

# --- Deutsche Zahlwörter ----------------------------------------------------
_ZAHLWORTE = {
    "zehn": 10, "zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40,
    "fünfzig": 50, "fuenfzig": 50, "hundert": 100, "zweihundert": 200,
    "dreihundert": 300, "fünfhundert": 500, "fuenfhundert": 500,
    "tausend": 1000, "zweitausend": 2000,
}

_PFLICHTFELDER = ["zielgruppe", "region", "lead_anzahl", "angebot"]

_RUECKFRAGEN = {
    "zielgruppe": "Welche Zielgruppe soll ich ansprechen? (z. B. Handwerker, IT-Dienstleister, Agenturen)",
    "region": "In welcher Region soll ich suchen? (z. B. NRW, München, Bayern)",
    "lead_anzahl": "Wie viele Leads soll ich finden? (z. B. 50, 100, 200)",
    "angebot": "Was möchtest du anbieten? (z. B. Website, SEO, Social Media)",
}


@dataclass
class IntakeErgebnis:
    """Ergebnis eines Intake-Durchlaufs.

    vollstaendig=True  → auftrag ist ein fertiger Entwurf, bereit zur Bestätigung.
    vollstaendig=False → fehlende_felder + rueckfrage, kontext für nächste Runde.
    """
    vollstaendig: bool
    auftrag: Optional[Auftrag] = None
    fehlende_felder: list[str] = field(default_factory=list)
    rueckfrage: str = ""
    kontext: dict = field(default_factory=dict)


class OperatorIntake:
    def __init__(self, llm_fn: Optional[LLMFn] = None):
        self._llm = llm_fn

    # ----------------------------------------------------------------- public

    def verstehe(self, text: str, kontext: Optional[dict] = None) -> IntakeErgebnis:
        """Versteht freien Text und füllt das Auftrags-Schema.

        kontext: bereits bekannte Felder aus früheren Dialogrunden (Mehrfach-Dialog).
        """
        felder = dict(kontext or {})

        neu = self._extrahieren(text)
        # Nur Felder ergänzen, die noch fehlen — bestehender Kontext gewinnt nicht
        # über explizite neue Angaben? Doch: neue, gezielte Antwort soll füllen.
        for k, v in neu.items():
            if v is not None and not felder.get(k):
                felder[k] = v

        fehlend = [f for f in _PFLICHTFELDER if not felder.get(f)]

        if fehlend:
            erstes = fehlend[0]
            return IntakeErgebnis(
                vollstaendig=False,
                fehlende_felder=fehlend,
                rueckfrage=_RUECKFRAGEN[erstes],
                kontext=felder,
            )

        auftrag = Auftrag(
            zielgruppe=felder["zielgruppe"],
            region=felder["region"],
            lead_anzahl=int(felder["lead_anzahl"]),
            angebot=felder["angebot"],
            qualitaet=Qualitaetskriterien(),
        )
        return IntakeErgebnis(vollstaendig=True, auftrag=auftrag, kontext=felder)

    # --------------------------------------------------------------- internal

    def _extrahieren(self, text: str) -> dict:
        """LLM-Pfad falls verfügbar, sonst deterministischer Parser."""
        if self._llm is not None:
            ergebnis = self._llm_extrahieren(text)
            if ergebnis is not None:
                return ergebnis
        return self._deterministisch_extrahieren(text)

    # --- deterministischer Parser ---

    def _deterministisch_extrahieren(self, text: str) -> dict:
        low = " " + text.lower().strip() + " "
        return {
            "lead_anzahl": self._finde_anzahl(low),
            "region": self._finde_region(low),
            "angebot": self._finde_angebot(low),
            "zielgruppe": self._finde_zielgruppe(low, text),
        }

    @staticmethod
    def _finde_anzahl(low: str) -> Optional[int]:
        m = re.search(r"\b(\d{1,5})\b", low)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 100000:
                return n
        for wort, wert in _ZAHLWORTE.items():
            if wort in low:
                return wert
        return None

    @staticmethod
    def _finde_region(low: str) -> Optional[str]:
        # Längere Synonyme zuerst prüfen (z. B. "nordrhein-westfalen" vor "nrw")
        for syn in sorted(_REGION_SYNONYME, key=len, reverse=True):
            if re.search(r"\b" + re.escape(syn) + r"\b", low):
                return _REGION_SYNONYME[syn]
        return None

    @staticmethod
    def _finde_angebot(low: str) -> Optional[str]:
        # Muster "<X>-Angebot(e)" / "<X>-angebote"
        m = re.search(r"([a-zäöüß]+)[- ]angebot", low)
        if m:
            wort = m.group(1)
            return _ANGEBOT_KEYWORDS.get(wort, wort.capitalize())
        for kw in sorted(_ANGEBOT_KEYWORDS, key=len, reverse=True):
            if re.search(r"\b" + re.escape(kw) + r"\b", low):
                return _ANGEBOT_KEYWORDS[kw]
        return None

    @staticmethod
    def _finde_zielgruppe(low: str, original: str) -> Optional[str]:
        # Bekannte Branchen (längere Synonyme zuerst)
        for syn in sorted(_BRANCHEN_SYNONYME, key=len, reverse=True):
            if re.search(r"\b" + re.escape(syn) + r"\b", low):
                return _BRANCHEN_SYNONYME[syn]
        # Fallback: Muster "an <X>" / "für <X>" (X = nächstes sinnvolles Wort)
        m = re.search(r"\b(?:an|für|fuer)\s+([A-Za-zÄÖÜäöüß]{3,})", original)
        if m:
            kandidat = m.group(1)
            # Häufige Füllwörter ausschließen
            if kandidat.lower() not in {"die", "der", "das", "den", "ein", "eine", "alle"}:
                return kandidat.capitalize()
        return None

    # --- LLM-Pfad ---

    def _llm_extrahieren(self, text: str) -> Optional[dict]:
        system = (
            "Du bist ein Extraktions-Modul für B2B-Lead-Aufträge. "
            "Du erhältst eine Kundennachricht auf Deutsch und gibst NUR ein JSON-Objekt "
            "mit diesen Feldern zurück: zielgruppe (Branche/ICP), region (Ort/Bundesland), "
            "lead_anzahl (Zahl oder null), angebot (was der Kunde verkauft). "
            "Felder, die nicht eindeutig genannt sind, auf null setzen. "
            "Keine Erklärungen, kein Text außerhalb des JSON."
        )
        user = f'Kundennachricht: "{text}"\n\nGib das JSON zurück.'
        try:
            antwort = self._llm(system, user)
            daten = self._json_aus_text(antwort)
            if daten is None:
                return None
            anzahl = daten.get("lead_anzahl")
            return {
                "zielgruppe": (daten.get("zielgruppe") or None),
                "region": (daten.get("region") or None),
                "lead_anzahl": int(anzahl) if anzahl else None,
                "angebot": (daten.get("angebot") or None),
            }
        except Exception:
            # Bei jedem LLM-Problem sauber auf den deterministischen Pfad zurückfallen
            return None

    @staticmethod
    def _json_aus_text(antwort: str) -> Optional[dict]:
        if not antwort:
            return None
        # JSON-Block aus eventuell umschließendem Text herauslösen
        m = re.search(r"\{.*\}", antwort, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
