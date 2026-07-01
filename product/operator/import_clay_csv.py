"""import_clay_csv.py — Merge-back der Clay-CSV → CRM-fertige Lead-Datei.

Liest die von Clay/Findymail angereicherte CSV, merged die Kontaktdaten per
Domain auf die bestehenden (reichen) Lead-Objekte aus dem letzten Lauf, sortiert
Leads ohne nutzbaren Kanal aus und schreibt eine CRM-fertige JSON.

NIEMALS import_cli.py (zerstört Premium-Felder). Dieser Merge fasst NUR
Kontaktfelder an — Briefing/Einwände/Mail/Score/premium_klasse bleiben.

BEISPIEL:
  py -3.14 product/operator/import_clay_csv.py --enriched product/operator/enriched.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from product.bridge import clay_import  # noqa: E402

_DEFAULT_QUELLE = _ROOT / "b2bbot" / "output" / "latest" / "signal_leads.json"
_DEFAULT_ZIEL = _ROOT / "product" / "operator" / "leads_crm_fertig.json"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Clay-angereicherte CSV auf die Leads mergen (Merge-back).")
    p.add_argument("--enriched", required=True, help="Pfad zur von Clay zurückgegebenen CSV.")
    p.add_argument("--quelle", default=str(_DEFAULT_QUELLE), help="Lead-Quelle (letzter Lauf).")
    p.add_argument("--ziel", default=str(_DEFAULT_ZIEL), help="CRM-fertige Ausgabe-JSON.")
    args = p.parse_args(argv)

    if not Path(args.enriched).exists():
        print(f"[import] FEHLER: enriched-CSV nicht gefunden: {args.enriched}", flush=True)
        return 2
    if not Path(args.quelle).exists():
        print(f"[import] FEHLER: Lead-Quelle nicht gefunden: {args.quelle}", flush=True)
        return 2

    enriched, smap = clay_import.lade_enriched_csv(args.enriched)
    leads = clay_import.lade_leads(args.quelle)

    print(f"[import] enriched-Zeilen: {len(enriched)} | Leads: {len(leads)}", flush=True)
    print(f"[import] Erkannte Clay-Spalten: "
          f"{ {feld: sp for feld, sp in smap.items() if feld in ('personal_email','email_status','mobile_phone')} }",
          flush=True)
    if "personal_email" not in smap and "mobile_phone" not in smap:
        print("[import] WARNUNG: Weder persönliche-Mail- noch Telefon-Spalte erkannt. "
              "Prüfe die CSV-Header und ergänze ggf. einen Alias in clay_import._ALIASES.", flush=True)

    auslieferbar, stats = clay_import.merge_und_filtern(leads, enriched, smap)
    print(f"[import] Stats: {stats}", flush=True)

    ziel = Path(args.ziel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(json.dumps({"leads": auslieferbar}, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8")
    print(f"[import] {len(auslieferbar)} CRM-fertige Leads -> {ziel}", flush=True)
    print("[import] Naechster Schritt: Datei ins CRM laden (Emilio macht den Liefer-Link).", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
