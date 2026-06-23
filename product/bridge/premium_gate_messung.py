"""Messskript — wirft das Premium-Gate auf den ECHTEN letzten Lauf und zeigt,
wie hart es filtert (PREMIUM/REVIEW/REJECT) und WARUM.

Aufruf (Python 3.14)::

    py -3.14 -m product.bridge.premium_gate_messung
    py -3.14 -m product.bridge.premium_gate_messung --datei <pfad> --zielbranche "IT-Dienstleister"

Liest nur (kein Schreiben, kein Netz). Ohne ``--zielbranche`` wird die
``zielgruppe`` aus der Lauf-Datei verwendet — so wird sichtbar, dass „Vertrieb"
als Rollenwort den ICP-Fit (noch) nicht prüfbar macht (Schritt 5).
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

from product.bridge import premium_gate as pg

_STANDARD_DATEI = Path("b2bbot/output/latest/signal_leads.json")


def _utf8_stdout() -> None:
    """Windows-Konsole ist oft cp1252 → Box-/Emoji-Zeichen würden crashen."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _laden(pfad: Path) -> dict:
    return json.loads(pfad.read_text(encoding="utf-8"))


def messen(pfad: Path, zielbranche: str | None) -> int:
    if not pfad.exists():
        print(f"❌ Datei nicht gefunden: {pfad}", file=sys.stderr)
        return 1
    daten = _laden(pfad)
    leads = daten.get("leads") if isinstance(daten, dict) else daten
    if not isinstance(leads, list):
        print("❌ Keine Lead-Liste in der Datei.", file=sys.stderr)
        return 1

    zb = zielbranche if zielbranche is not None else str(daten.get("zielgruppe") or "")
    print("═" * 72)
    print(f"PREMIUM-GATE MESSUNG  ·  {pfad}")
    print(f"Leads: {len(leads)}  ·  Zielbranche/-gruppe: „{zb}“")
    print("═" * 72)

    klassen = collections.Counter()
    # Vorher-Bild: die (zu weiche) bisherige Kaufbereitschafts-Stufe.
    vorher_stufe = collections.Counter(
        str(l.get("kaufbereitschaft_stufe") or "—").lower() for l in leads)
    grund_zaehler = collections.Counter()
    beispiele: dict[str, list[tuple[str, list[str]]]] = {
        pg.PREMIUM: [], pg.REVIEW: [], pg.REJECT: []}

    for lead in leads:
        r = pg.bewerten_premium(lead, zielbranche=zb)
        klassen[r["klasse"]] += 1
        for g in r["kills"] + r["premium_miss"]:
            grund_zaehler[_grund_kategorie(g)] += 1
        firma = (lead.get("company_name") or lead.get("company_name_clean")
                 or "—").strip()
        if len(beispiele[r["klasse"]]) < 6:
            beispiele[r["klasse"]].append((firma, r["gruende"]))

    print("\n▶ VORHER (bisherige kaufbereitschaft_stufe — zu weich):")
    for stufe in ("hoch", "mittel", "niedrig"):
        print(f"    {stufe:<8} {vorher_stufe.get(stufe, 0)}")

    print("\n▶ NACHHER (Premium-Gate):")
    n = len(leads) or 1
    for klasse in (pg.PREMIUM, pg.REVIEW, pg.REJECT):
        c = klassen.get(klasse, 0)
        print(f"    {klasse:<8} {c:>3}   ({100*c//n:>3} %)")

    print("\n▶ WARUM nicht Premium — häufigste Gründe (Mehrfachnennung je Lead):")
    for grund, c in grund_zaehler.most_common():
        print(f"    {c:>3}×  {grund}")

    for klasse in (pg.PREMIUM, pg.REVIEW, pg.REJECT):
        if not beispiele[klasse]:
            continue
        print(f"\n▶ Beispiele {klasse}:")
        for firma, gruende in beispiele[klasse]:
            print(f"    • {firma}")
            for g in gruende[:3]:
                print(f"        – {g}")
    print("═" * 72)
    return 0


def _grund_kategorie(grund: str) -> str:
    """Verdichtet einen Einzel-Grund auf eine zählbare Kategorie."""
    g = grund.lower()
    if "ready_to_send=no" in g:
        return "Engine: ready_to_send=no"
    if "icp-fit nicht prüfbar" in g or "rollen-/funktionswort" in g:
        return "ICP-Fit nicht prüfbar (Zielbranche = Rollenwort)"
    if "branche passt nicht" in g:
        return "ICP-Branche passt nicht"
    if "rollen-/sammel-mail" in g:
        return "nur Rollen-/Sammel-Mail, kein Telefon"
    if "fake/bounce" in g or "e-mail-rang" in g:
        return "E-Mail-Rang Fake/Bounce-Klasse"
    if "veraltet" in g:
        return "Beleg veraltet (>90 Tage)"
    if "echte firmen-website" in g:
        return "keine echte Website"
    if "artefakt" in g:
        return "Artefakt in Firma/Name"
    if "kein signal" in g:
        return "kein Signal/Beleg"
    if "ohne nachprüfbaren beleg" in g:
        return "Signal ohne Beleg-URL"
    if "kein kontakt" in g:
        return "kein Kontakt"
    if "sende-block" in g or "do_not_contact" in g:
        return "harter Sende-Block"
    return grund[:48]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Premium-Gate am echten Lauf messen.")
    p.add_argument("--datei", type=Path, default=_STANDARD_DATEI)
    p.add_argument("--zielbranche", default=None,
                   help="echte Zielbranche (sonst: zielgruppe aus der Datei)")
    args = p.parse_args(argv)
    _utf8_stdout()
    return messen(args.datei, args.zielbranche)


if __name__ == "__main__":
    raise SystemExit(main())
