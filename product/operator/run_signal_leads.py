"""run_signal_leads.py — DER gesegnete Einstiegspunkt für Lead-Erzeugung.

Ein einziger, parametrisierter Lauf über ``engine_bridge.suchen_per_signal``
(Signal + Firma + Zentrale-Telefon aus Impressum, gratis) mit ``SIGNAL_NUR_PREMIUM=1``.
Am Ende wird direkt die Clay-CSV (``leads_fuer_clay.csv``) geschrieben — damit
Hermes/Emilio in EINEM Schritt vom Auftrag zur Enrichment-fertigen Liste kommt.

WARUM DIESER EINSTIEGSPUNKT (Bauplan Sofort-Fix B + Governance):
- Lead-Erzeugung NUR hierüber (nie Klassik-b2bbot `mine.py` — der geht am Gate vorbei).
- Liefert die Nische zu wenig echte Premium, sucht die eingebaute Eskalation
  (Stadt → deutschlandweit) SELBST breiter — es wird NIE mit Müll aufgefüllt.
- b2bbot bleibt READ-ONLY.

BEISPIELE:
  py -3.14 product/operator/run_signal_leads.py --zielgruppe Vertrieb --region Braunschweig --anzahl 15
  py -3.14 product/operator/run_signal_leads.py --gruppe versicherung --zielgruppe Handwerk --region Leipzig --anzahl 15
  py -3.14 product/operator/run_signal_leads.py --zielgruppe Vertrieb --branche-egal --signale sales_hiring,appointment_setter
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from product.bridge import angebot_signale as _as  # noqa: E402
from product.operator.order_schema import Auftrag  # noqa: E402


def _signale_bestimmen(gruppe: str, override: str) -> list[str]:
    """Signal-Set: expliziter Override gewinnt, sonst das Default-Preset der Gruppe."""
    if override.strip():
        return [s.strip() for s in override.split(",") if s.strip()]
    angebot_id = "versicherung" if gruppe == _as.GRUPPE_VERSICHERUNG else "vertrieb"
    return list(_as._GRUPPE_DEFAULT.get(_as.gruppe_fuer_angebot(angebot_id), ("sales_hiring",)))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Premium-Signal-Leads erzeugen (Einstiegspunkt).")
    p.add_argument("--zielgruppe", default="Vertrieb", help="Zielbranche ODER Rollenwort (z.B. 'Vertrieb', 'Handwerk').")
    p.add_argument("--region", default="", help="Startstadt; eskaliert automatisch DE-weit. Leer = direkt DE-weit.")
    p.add_argument("--anzahl", type=int, default=15, help="Bestellte Menge (Gate ist streng ~ ergibt weniger).")
    p.add_argument("--gruppe", default="vertrieb", choices=["vertrieb", "versicherung"],
                   help="Angebots-Gruppe (bestimmt Signal-Preset + ICP).")
    p.add_argument("--signale", default="", help="Override, kommagetrennt (z.B. 'sales_hiring,appointment_setter').")
    p.add_argument("--branche-egal", action="store_true", help="ICP breit/horizontal (Zielgruppe optional).")
    p.add_argument("--kein-linkedin", action="store_true", help="LinkedIn-URL-Anreicherung aus (spart 1 Serper/Lead).")
    p.add_argument("--kein-export", action="store_true", help="Keine Clay-CSV am Ende schreiben.")
    p.add_argument("--faktor", default="2", help="SIGNAL_UEBERSUCH_FAKTOR (Serper-Spar; Default 2 statt 3).")
    args = p.parse_args(argv)

    # Harte Regeln als Env (nur PREMIUM ausliefern, Serper sparen).
    import os
    os.environ["PYTHONUTF8"] = "1"
    os.environ["SIGNAL_NUR_PREMIUM"] = "1"
    os.environ["SIGNAL_UEBERSUCH_FAKTOR"] = str(args.faktor)

    from product.bridge.engine_bridge import EngineBridge

    gruppe = _as.GRUPPE_VERSICHERUNG if args.gruppe == "versicherung" else _as.GRUPPE_VERTRIEB
    signale = _signale_bestimmen(gruppe, args.signale)
    angebot = "versicherung" if gruppe == _as.GRUPPE_VERSICHERUNG else "Susi"

    bridge = EngineBridge(engine_dir=str(_ROOT / "b2bbot"))
    auftrag = Auftrag(
        zielgruppe=args.zielgruppe,
        region=args.region,
        lead_anzahl=args.anzahl,
        angebot=angebot,
    )
    auftrag.bestaetigen()

    print(f"[{time.strftime('%H:%M:%S')}] START | Gruppe={gruppe} | Zielgruppe='{args.zielgruppe}' "
          f"| Region='{args.region or 'DE-weit'}' | Signale={signale} | NUR Premium | "
          f"{'LinkedIn aus' if args.kein_linkedin else 'LinkedIn an'}", flush=True)

    result = bridge.suchen_per_signal(
        auftrag=auftrag,
        signal_typ=signale,
        laender=("de",),
        linkedin_web=not args.kein_linkedin,
        branche_egal=bool(args.branche_egal),
    )

    leads = (result.rohdaten or {}).get("leads", []) if result.ok else []
    summary = {
        "ok": result.ok,
        "leads_gefunden": result.leads_gefunden,
        "leads_premium": result.leads_sauber,
        "meldung": result.meldung,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    print(f"[{time.strftime('%H:%M:%S')}] FERTIG: {summary}", flush=True)

    if not args.kein_export and result.ok and leads:
        from product.operator import export_clay_csv
        export_clay_csv.main([])           # liest latest/signal_leads.json -> leads_fuer_clay.csv
    elif not leads:
        print("[run] Keine Premium-Leads — keine CSV geschrieben. Nische dünn oder Region zu eng.", flush=True)

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
