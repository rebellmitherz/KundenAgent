"""Signal-Leads personalisieren — Aufhänger ans Lead heften + Mail rendern.

Verbindet die zwei vorhandenen Schichten:
  - `aufhaenger.py` (Regeln + OpenAI) liefert den Einstiegssatz pro Lead.
  - Der b2bbot-Builder `build_hardened_outreach_messages_for_lead` baut daraus —
    über den `{aufhaenger}`-Platzhalter im aktiven Profil — die fertige Erstmail.

Das Lead-Feld ``aufhaenger`` wird IMMER gesetzt (auch leer = generische Mail).
Die gerenderte Vorschau (`personalisierte_mail`) ist optional und defensiv: ein
Engine-Fehler darf die Signal-Suche nie kippen.

Kein Versand. Der Builder liest nur Lead-Daten + Profil-Env (read-only Engine).
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Optional

from product.personalization.aufhaenger import aufhaenger_text

# Builder-Signatur: lead -> {"first_email_subject", "first_email_body", ...}
Builder = Callable[[dict], dict]


def angebot_aus_profil_id(profil_id: str) -> str:
    """Leitet den Angebot-Typ aus der aktiven Profil-ID ab (für die Aufhänger-Regeln)."""
    pid = (profil_id or "").lower()
    if "website" in pid or "webseite" in pid:
        return "website"
    if "akquise" in pid or "termin" in pid:
        return "akquise"
    return "kundenagent"


def _ansprechpartner(lead: dict) -> str:
    return (lead.get("contact_full_name") or lead.get("managing_director") or "").strip()


def personalisiere(leads: list[dict], angebot_typ: str, *, llm: Optional[Callable[[str], str]] = None) -> int:
    """Setzt ``lead['aufhaenger']`` für jeden Lead (in-place). Gibt Zahl mit Aufhänger zurück."""
    n = 0
    for lead in leads:
        satz = aufhaenger_text(
            lead, angebot_typ, llm=llm,
            firma=(lead.get("company_name") or "").strip(),
            branche=(lead.get("industry") or lead.get("target_industry") or "").strip(),
            ansprechpartner=_ansprechpartner(lead),
        )
        lead["aufhaenger"] = satz
        if satz:
            n += 1
    return n


@contextmanager
def _env(overrides: Optional[dict]):
    """Setzt Profil-Env temporär (für den Engine-Builder), danach exakt zurück."""
    alt: dict[str, Optional[str]] = {}
    for k, v in (overrides or {}).items():
        alt[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        yield
    finally:
        for k, old in alt.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def _engine_builder(engine_dir: str | Path) -> Builder:
    """Lädt den echten b2bbot-Builder über den Engine-Kontext (read-only)."""
    from product.bridge.signal_discovery import _engine_context

    def _call(lead: dict) -> dict:
        with _engine_context(Path(engine_dir)):
            from modules.outreach_pipeline import build_hardened_outreach_messages_for_lead
            return build_hardened_outreach_messages_for_lead(lead)

    return _call


def rendere_mail(
    lead: dict,
    engine_dir: str | Path,
    profil_env: Optional[dict] = None,
    *,
    _builder: Optional[Builder] = None,
) -> dict:
    """Rendert Betreff + Body mit gesetztem Aufhänger über den Engine-Builder.

    Defensiv: bei jedem Fehler {} (Signal-Suche läuft trotzdem weiter). `_builder`
    ist für Tests injizierbar (kein Engine-Import nötig).
    """
    try:
        builder = _builder or _engine_builder(engine_dir)
        with _env(profil_env or {}):
            msgs = builder(lead) or {}
        body = (msgs.get("first_email_body") or "").strip()
        if not body:
            return {}
        return {
            "betreff": (msgs.get("first_email_subject") or "").strip(),
            "body": body,
        }
    except Exception:
        return {}


def personalisiere_und_rendere(
    leads: list[dict],
    angebot_typ: str,
    engine_dir: str | Path,
    profil_env: Optional[dict] = None,
    *,
    llm: Optional[Callable[[str], str]] = None,
    _builder: Optional[Builder] = None,
) -> int:
    """Komplett: Aufhänger heften + personalisierte Vorschau-Mail rendern (in-place).

    Setzt ``lead['aufhaenger']`` und (falls renderbar) ``lead['personalisierte_mail']``.
    Gibt die Zahl der Leads mit Aufhänger zurück.
    """
    n = personalisiere(leads, angebot_typ, llm=llm)
    for lead in leads:
        mail = rendere_mail(lead, engine_dir, profil_env, _builder=_builder)
        if mail:
            lead["personalisierte_mail"] = mail
    return n
