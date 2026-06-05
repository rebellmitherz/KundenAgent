"""Signalqualität — Termin-Triage gegen Fehlalarme (Phase F1).

Warum diese Schicht existiert
------------------------------
Der Motor (`reply_intelligence` der Engine) markiert manche Antworten als
``appointment_ready`` / ``positive``, obwohl der Text eine klare Absage ist.
Belegt im Live-Datensatz: eine Antwort *"Daher haben wir aktuell keinen Bedarf"*
kam als ``inbound_class=positive`` + ``appointment_ready=true`` herein
(``b2bbot/output/latest/reply_queue.json``). Ungeprüft würde das Produkt das als
Termin melden — und **ein einziger solcher Fehlalarm kostet beim Kunden das
Vertrauen** (HANDOFF §6: "Immer ehrlich. Nie faken.").

Was diese Schicht tut
---------------------
Sie bewertet JEDES Termin-Signal noch einmal gegen den Antworttext, bevor es als
*bestätigter* Termin gemeldet wird. Drei mögliche Stufen:

  - ``"bestaetigt"`` — echtes Termin-Signal, darf laut gemeldet werden.
  - ``"pruefen"``    — widersprüchlich (Absage-Formulierung oder Auto-Antwort);
                       wird dem Menschen leise zur Prüfung vorgelegt, NIE als
                       sicherer Termin verkauft.
  - ``"kein"``       — kein Terminwunsch.

Muster wie überall im Code: **deterministische Regel zuerst** (läuft ohne Key,
Tests deterministisch), **LLM optional als Verschärfung** mit sauberem Fallback.
Konservativ ausgelegt: im Zweifel lieber herabstufen als einen Fehlalarm senden,
aber nur bei *klaren* Absage-Hinweisen — echte Termine bleiben "bestaetigt".
"""
from __future__ import annotations

from typing import Callable, Optional

# ─── Status-Konstanten ───────────────────────────────────────────────────────

BESTAETIGT = "bestaetigt"
PRUEFEN = "pruefen"
KEIN = "kein"


# ─── Absage-Erkennung (deterministisch, hohe Präzision) ──────────────────────

# Klare Absage-/Desinteresse-Formulierungen. Bewusst eng gehalten: jeder Eintrag
# soll fast nur in echten Absagen vorkommen, damit echte Termine nicht
# fälschlich herabgestuft werden. Alles wird gegen kleingeschriebenen Text geprüft.
ABSAGE_HINWEISE: frozenset[str] = frozenset({
    "kein bedarf",
    "keinen bedarf",
    "kein interesse",
    "keinen interesse",
    "nicht interessiert",
    "kein interesse besteht",
    "besteht kein interesse",
    "aktuell kein",
    "derzeit kein",
    "zurzeit kein",
    "momentan kein",
    "haben wir bereits",
    "arbeiten bereits mit",
    "nicht kontaktieren",
    "keine werbung",
    "bitte um löschung",
    "bitte löschen sie",
    "austragen",
    "abmelden",
    "no interest",
    "not interested",
    "unsubscribe",
    "please remove",
})


def _normalisieren(text: str) -> str:
    return " ".join((text or "").lower().split())


def enthaelt_absage(text: str) -> bool:
    """True, wenn der Text eine klare Absage-/Desinteresse-Formulierung enthält."""
    norm = _normalisieren(text)
    if not norm:
        return False
    return any(hinweis in norm for hinweis in ABSAGE_HINWEISE)


def _ist_auto(antwort: dict) -> bool:
    # Bridge mappt is_auto_reply → auto_antwort; beide Felder berücksichtigen.
    return bool(antwort.get("auto_antwort") or antwort.get("is_auto_reply"))


def _antworttext(antwort: dict) -> str:
    """Sammelt den prüfbaren Text einer Antwort (Auszug + Betreff + Grund)."""
    teile = [
        antwort.get("auszug", ""),
        antwort.get("betreff", ""),
        antwort.get("termin_grund", ""),
    ]
    return " ".join(t for t in teile if t)


# ─── Triage einer einzelnen Antwort ──────────────────────────────────────────


def termin_status(antwort: dict, llm_fn: Optional[Callable[[str, str], str]] = None) -> str:
    """Bewertet eine Antwort: BESTAETIGT | PRUEFEN | KEIN.

    Reihenfolge (fail-safe Richtung "ehrlich"):
      1. Kein Terminwunsch        → KEIN
      2. Auto-Antwort (OOO)       → PRUEFEN  (eine Abwesenheitsnotiz ist nie ein Termin)
      3. Klare Absage im Text     → PRUEFEN  (Fehlalarm der Engine abfangen)
      4. LLM verfügbar            → LLM bestätigt/verwirft (Fallback: BESTAETIGT)
      5. sonst                    → BESTAETIGT
    """
    if not antwort.get("terminwunsch"):
        return KEIN

    if _ist_auto(antwort):
        return PRUEFEN

    text = _antworttext(antwort)
    if enthaelt_absage(text):
        return PRUEFEN

    if llm_fn is not None:
        urteil = _llm_urteil(llm_fn, antwort, text)
        if urteil in (BESTAETIGT, PRUEFEN):
            return urteil

    return BESTAETIGT


def _llm_urteil(llm_fn, antwort: dict, text: str) -> Optional[str]:
    """Fragt das LLM, ob die Antwort wirklich ein Termin-/Gesprächswunsch ist.

    Bei jeder Unsicherheit (Fehler, unklare Antwort) → None, sodass die
    deterministische Vorentscheidung (BESTAETIGT) bestehen bleibt.
    """
    system = (
        "Du prüfst, ob eine eingegangene B2B-E-Mail-Antwort wirklich Interesse an "
        "einem Termin oder Gespräch signalisiert. Absagen, Desinteresse, "
        "Abwesenheitsnotizen oder reine Höflichkeit sind KEIN Termin. "
        "Antworte mit genau einem Wort: JA (echter Termin/Interesse) oder "
        "NEIN (kein echter Termin)."
    )
    user = f"Firma: {antwort.get('firma', '?')}\nAntworttext:\n{text[:1500]}"
    try:
        roh = (llm_fn(system, user) or "").strip().lower()
    except Exception:
        return None
    if roh.startswith("ja"):
        return BESTAETIGT
    if roh.startswith("nein"):
        return PRUEFEN
    return None


# ─── Triage einer Liste ──────────────────────────────────────────────────────


def triage(
    antworten: list[dict], llm_fn: Optional[Callable[[str, str], str]] = None
) -> dict:
    """Bewertet alle Antworten und teilt die Termin-Signale in zwei Töpfe.

    Schreibt zusätzlich ``termin_status`` in jede Antwort (für Anzeige/Debug)
    und überspringt erledigte Termine.

    Rückgabe:
      {"bestaetigt": [...echte Termine...], "pruefen": [...zur Prüfung...]}
    """
    bestaetigt: list[dict] = []
    pruefen: list[dict] = []
    for a in antworten:
        status = termin_status(a, llm_fn=llm_fn)
        a["termin_status"] = status
        if a.get("erledigt"):
            continue
        if status == BESTAETIGT:
            bestaetigt.append(a)
        elif status == PRUEFEN:
            pruefen.append(a)
    return {"bestaetigt": bestaetigt, "pruefen": pruefen}
