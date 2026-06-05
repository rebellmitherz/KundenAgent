"""Revenue-Reporting pro Mandant + Operator-Gesamtsicht (F5).

Hero-Metrik: geprüfte Termine (aus F1-Triage), nicht rohe Lead-Menge.
Pro Mandant: Termine + Prüf-Queue + Funnel + Antworten ohne Bezug.
Gesamtsicht: Tabelle über alle aktiven Mandanten für den Betreiber.

Reine Aggregation auf vorhandenen Runner-Methoden — kein neuer Akquise-Code.
"""
from __future__ import annotations

from typing import Optional

from product.platform.plattform import Plattform


# ─── Pro-Mandant-Report ───────────────────────────────────────────────────────


def mandant_report(mandant_id: str, plattform: Plattform) -> dict:
    """Kennzahlen eines einzelnen Mandanten.

    Gibt immer ein vollständiges Dict zurück — fehlerhafte Runner liefern Nullen.
    """
    runner = plattform.runner_oder_none(mandant_id)
    if runner is None:
        return {
            "mandant_id": mandant_id,
            "betriebsbereit": False,
            "termine_bestaetigt": 0,
            "termine_pruefen": 0,
            "antworten_gesamt": 0,
            "antwort_ohne_bezug": 0,
            "termin_ohne_bezug": 0,
            "funnel": {},
            "error": "nicht eingerichtet oder Engine fehlt",
        }

    try:
        ant = runner.antworten()
        funnel = runner.funnel()
        return {
            "mandant_id": mandant_id,
            "betriebsbereit": True,
            "termine_bestaetigt": len(runner.termin_signale()),
            "termine_pruefen": len(runner.pruef_termine()),
            "antworten_gesamt": len(ant),
            "antwort_ohne_bezug": funnel.get("antwort_ohne_bezug", 0),
            "termin_ohne_bezug": funnel.get("termin_ohne_bezug", 0),
            "funnel": funnel.get("stufen", {}),
            "error": "",
        }
    except Exception as exc:
        return {
            "mandant_id": mandant_id,
            "betriebsbereit": True,
            "termine_bestaetigt": 0,
            "termine_pruefen": 0,
            "antworten_gesamt": 0,
            "antwort_ohne_bezug": 0,
            "termin_ohne_bezug": 0,
            "funnel": {},
            "error": str(exc),
        }


def mandant_report_text(report: dict, name: str = "") -> str:
    """Kundenfähiger Einzel-Report: ehrlich, knapp, umsatzfokussiert."""
    anzeige = name or report["mandant_id"]
    if not report["betriebsbereit"]:
        return f"⚙️ {anzeige}: noch nicht eingerichtet."

    t = report["termine_bestaetigt"]
    p = report["termine_pruefen"]
    a = report["antworten_gesamt"]
    ob = report["antwort_ohne_bezug"]
    tob = report["termin_ohne_bezug"]
    f = report["funnel"]

    zeilen = [f"📊 {anzeige}"]

    # Hero-Zeile: geprüfte Termine als primäre Zahl
    if t:
        zeilen.append(f"   🎯 {t} bestätigter Termin{'e' if t != 1 else ''}")
    if p:
        zeilen.append(f"   🔎 {p} zur Prüfung (Antwort widersprüchlich)")

    # Funnel-Zeile
    angeschr = f.get("angeschrieben", 0)
    geantw = f.get("geantwortet", 0)
    zeilen.append(
        f"   📧 {angeschr} angeschrieben · "
        f"💬 {a} Antwort{'en' if a != 1 else ''} · "
        f"↩️  {geantw} im Funnel"
    )

    # Ältere Kampagnen (ohne Bezug)
    if ob:
        hinweis = f"   ⚠️  {ob} Antwort{'en' if ob != 1 else ''} aus früherer Kampagne"
        if tob:
            hinweis += f" ({tob} mit Termin-Signal)"
        zeilen.append(hinweis + " — 'Antworten zeigen'")

    if not t and not p and not a:
        zeilen.append("   Noch keine Aktivität.")

    return "\n".join(zeilen)


# ─── Operator-Gesamtsicht ─────────────────────────────────────────────────────


def plattform_report(plattform: Plattform) -> list[dict]:
    """Report über ALLE aktiven Mandanten — für den Betreiber."""
    berichte = []
    for mandant in plattform.register.alle(nur_aktive=True):
        berichte.append(mandant_report(mandant.mandant_id, plattform))
    return berichte


def plattform_report_text(plattform: Plattform) -> str:
    """Operator-Gesamtsicht: kompakte Tabelle, sortiert nach Termin-Signalen."""
    mandanten = plattform.register.alle(nur_aktive=True)
    if not mandanten:
        return "📋 Keine aktiven Mandanten registriert."

    berichte = plattform_report(plattform)

    # Sortierung: Termine absteigend → dann nach Name
    berichte.sort(key=lambda r: (-r["termine_bestaetigt"], r["mandant_id"]))

    gesamt_termine = sum(r["termine_bestaetigt"] for r in berichte)
    gesamt_pruefen = sum(r["termine_pruefen"] for r in berichte)
    gesamt_antworten = sum(r["antworten_gesamt"] for r in berichte)

    zeilen = [
        "━━━ Plattform-Übersicht ━━━",
        f"👥 {len(mandanten)} aktive Mandanten",
        f"🎯 {gesamt_termine} bestätigte Termine",
        f"🔎 {gesamt_pruefen} zur Prüfung",
        f"💬 {gesamt_antworten} Antworten gesamt",
        "",
    ]

    name_map = {m.mandant_id: (m.name or m.mandant_id) for m in mandanten}
    for r in berichte:
        name = name_map.get(r["mandant_id"], r["mandant_id"])
        if not r["betriebsbereit"]:
            zeilen.append(f"   ⚙️  {name}: nicht eingerichtet")
            continue
        t = r["termine_bestaetigt"]
        p = r["termine_pruefen"]
        a = r["antworten_gesamt"]
        status = "🎯" if t else ("🔎" if p else ("💬" if a else "·"))
        detail = f"{t}T" if t else ""
        if p:
            detail += f" {p}?"
        if a:
            detail += f" {a}A"
        zeilen.append(f"   {status} {name:<20} {detail or '—'}")

    return "\n".join(zeilen)
