"""CLI: Signal-Leads → Clay-Input-CSV (Teil 1 der Kontakt-Anreicherungs-Pipeline).

Ablauf gesamt:
    KundenAgent -> export.csv -> [Clay/Findymail: pers. Mail + Durchwahl] ->
    enriched.csv -> KundenAgent (Merge-back, Teil 2) -> Gate -> CRM.

Dieses Skript ist Teil 1: es liest die Leads des letzten Signal-Laufs und schreibt
die CSV mit dem Spalten-Vertrag (siehe clay_export.CLAY_SPALTEN). Kein Gate, keine
API, keine Kosten.

Aufruf:
    py -3.14 product/operator/export_clay_csv.py [QUELLE_JSON] [ZIEL_CSV]

Default-Quelle : b2bbot/output/latest/signal_leads.json  (letzter Lauf)
Default-Ziel   : product/operator/leads_fuer_clay.csv
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from product.bridge import clay_export as ce

_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_QUELLE = _ROOT / "b2bbot" / "output" / "latest" / "signal_leads.json"
_DEFAULT_ZIEL = _ROOT / "product" / "operator" / "leads_fuer_clay.csv"


def main(argv: list[str]) -> int:
    quelle = Path(argv[1]) if len(argv) > 1 else _DEFAULT_QUELLE
    ziel = Path(argv[2]) if len(argv) > 2 else _DEFAULT_ZIEL

    if not quelle.exists():
        print(f"[export] QUELLE nicht gefunden: {quelle}")
        print("         Erst einen Signal-Lauf machen oder Quelle als Argument angeben.")
        return 1

    leads = ce.lade_leads(quelle)
    if not leads:
        print(f"[export] Keine Leads in {quelle}.")
        return 1

    # Split: Leads mit schon vorhandener persoenlicher Mail (z. B. via harvestapi)
    # brauchen KEIN Clay -> nur die uebrigen kommen in die Clay-Input-CSV.
    geloest = [l for l in leads if ce.hat_persoenliche_mail(l)]
    rest = [l for l in leads if not ce.hat_persoenliche_mail(l)]

    n = ce.leads_zu_csv(rest, ziel)
    mit_name = sum(1 for l in rest if (l.get("contact_full_name") or l.get("managing_director") or "").strip())
    mit_domain = sum(1 for l in rest if (l.get("website") or "").strip())
    print(f"[export] {len(leads)} Leads gesamt: {len(geloest)} schon mit persoenl. Mail (kein Clay noetig) "
          f"| {n} an Clay -> {ziel}")
    if rest:
        print(f"[export] Clay-Rest: mit Ansprechpartner-Name: {mit_name}/{n} | mit Domain: {mit_domain}/{n}")
        print("[export] Naechster Schritt: diese CSV in Clay hochladen -> nur pers. Mail (+ Ansprechpartner).")
    else:
        print("[export] Alle Leads haben eine persoenliche Mail - Clay-Schritt entfaellt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
