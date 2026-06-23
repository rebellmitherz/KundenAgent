"""Suchen-Speicher für Signal-Leads (Weg-2-Tiefe).

Früher überschrieb jede Signal-Suche die vorige (`signal_leads.json` = nur der
letzte Lauf). Michael will: jede Suche bleibt erhalten, ist **getaggt** (welche
Suche?), und sowohl **ganze Suchen** als auch **einzelne Leads** sind löschbar —
damit sich nicht endlos Müll ansammelt.

Datenmodell (``output/latest/signal_runs.json``):

    {"runs": [ {run_id, generated_at, zielgruppe, region, laender, signal_typ,
                label, leads: [ {<engine-lead>, lead_id, run_id} ]} ]}

- Neueste Suche zuerst. Hart gedeckelt auf ``_MAX_RUNS`` (Schutz gegen Wildwuchs).
- Jeder Lead bekommt eine stabile ``lead_id`` (``<run_id>#<index>``) — Lösch-/
  Edit-Operationen laufen über die ID, nie über die Position.

Reine Produkt-Schicht, Engine unberührt. Defensiv: ein kaputter Store kippt nie
den Suchlauf (Lesen gibt im Zweifel leere Liste).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

_MAX_RUNS = 50          # so viele Suchen werden behalten (älteste fallen raus)
_MAX_LEADS_PRO_RUN = 200

# Felder, die der Mensch im Dashboard ändern darf (Inline-Edit).
_EDIT_FELDER = {
    "company_name", "phone", "email", "contact_full_name", "notiz", "aufhaenger",
}


def _store_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "latest" / "signal_runs.json"


def _load(path: Path) -> dict:
    # Haupt-Datei zuerst, dann die .bak-Sicherung (Recovery, falls die Haupt-
    # Datei durch einen abgebrochenen Schreibvorgang leer/kaputt ist). So gehen
    # gespeicherte Suchen nicht verloren, nur weil ein Schreiben schiefging.
    for p in (path, path.with_suffix(path.suffix + ".bak")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("runs"), list):
                return data
        except Exception:
            continue
    return {"runs": []}


def _save(path: Path, data: dict) -> None:
    """Schreibt den Store ATOMAR. Vorher überschrieb ein abgebrochener oder mit
    einem zweiten Lauf überlappender ``write_text`` die Datei mittendrin → sie
    wurde leer und ALLE bisherigen Suchen waren weg (genau der „letzte Suche
    plötzlich verschwunden"-Effekt). Jetzt: in temp schreiben, alten Stand als
    .bak sichern, dann atomar per ``os.replace`` einsetzen."""
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(txt, encoding="utf-8")
    try:
        if path.exists():
            os.replace(path, path.with_suffix(path.suffix + ".bak"))
    except OSError:
        pass
    os.replace(tmp, path)


def append_run(output_dir: str | Path, *, run_id: str, meta: dict, leads: list[dict]) -> str:
    """Hängt einen Suchlauf an (neueste zuerst). Vergibt lead_id je Lead.
    Gibt die run_id zurück. Idempotent: gleiche run_id ersetzt den alten Eintrag."""
    path = _store_path(output_dir)
    data = _load(path)
    leads = list(leads or [])[:_MAX_LEADS_PRO_RUN]
    for i, l in enumerate(leads):
        if isinstance(l, dict):
            l["lead_id"] = f"{run_id}#{i}"
            l["run_id"] = run_id
    run = {**(meta or {}), "run_id": run_id, "leads": leads}
    runs = [r for r in data.get("runs", []) if r.get("run_id") != run_id]
    runs.insert(0, run)
    data["runs"] = runs[:_MAX_RUNS]
    _save(path, data)
    return run_id


def list_runs(output_dir: str | Path) -> list[dict]:
    return _load(_store_path(output_dir)).get("runs", [])


def delete_run(output_dir: str | Path, run_id: str) -> int:
    """Löscht eine ganze Suche. Gibt zurück, wie viele Runs entfernt wurden (0/1)."""
    path = _store_path(output_dir)
    data = _load(path)
    vorher = len(data.get("runs", []))
    data["runs"] = [r for r in data.get("runs", []) if r.get("run_id") != run_id]
    _save(path, data)
    return vorher - len(data["runs"])


def delete_lead(output_dir: str | Path, lead_id: str) -> int:
    """Löscht einen einzelnen Lead über seine lead_id. Leere Suchen fallen weg.
    Gibt die Zahl der entfernten Leads zurück (0/1)."""
    path = _store_path(output_dir)
    data = _load(path)
    removed = 0
    for r in data.get("runs", []):
        leads = r.get("leads", [])
        neu = [l for l in leads if l.get("lead_id") != lead_id]
        removed += len(leads) - len(neu)
        r["leads"] = neu
    data["runs"] = [r for r in data.get("runs", []) if r.get("leads")]
    _save(path, data)
    return removed


def update_lead(output_dir: str | Path, lead_id: str, fields: dict) -> int:
    """Ändert erlaubte Felder eines Leads (Inline-Edit). Gibt 0/1 zurück."""
    path = _store_path(output_dir)
    data = _load(path)
    changed = 0
    for r in data.get("runs", []):
        for l in r.get("leads", []):
            if l.get("lead_id") == lead_id:
                for k, v in (fields or {}).items():
                    if k in _EDIT_FELDER:
                        l[k] = v
                        changed = 1
    if changed:
        _save(path, data)
    return changed


def migrate_einzeldatei(output_dir: str | Path, einzel_payload: Optional[dict]) -> bool:
    """Übernimmt einmalig den letzten Lauf aus ``signal_leads.json`` in den Store,
    falls dieser noch leer ist — damit der bestehende Treffer nicht „verschwindet".
    Gibt True zurück, wenn migriert wurde."""
    if not einzel_payload or not einzel_payload.get("leads"):
        return False
    path = _store_path(output_dir)
    if _load(path).get("runs"):
        return False
    run_id = str(einzel_payload.get("auftrag_id") or "migriert")
    meta = {
        "generated_at": einzel_payload.get("generated_at", ""),
        "zielgruppe": einzel_payload.get("zielgruppe", ""),
        "region": einzel_payload.get("region", ""),
        "laender": einzel_payload.get("laender", []),
        "signal_typ": einzel_payload.get("signal_typ", ""),
        "label": run_label(einzel_payload),
    }
    append_run(output_dir, run_id=run_id, meta=meta, leads=einzel_payload.get("leads", []))
    return True


def run_label(meta: dict) -> str:
    """Lesbares Such-Etikett: „Branche · Ort/Land · Signal · 17.06. 15:50"."""
    zg = (meta.get("zielgruppe") or "").strip()
    region = (meta.get("region") or "").strip()
    laender = meta.get("laender") or []
    wo = region or (", ".join(str(l).upper() for l in laender) if laender else "")
    teile = [t for t in [zg, wo, (meta.get("signal_typ") or "").strip()] if t]
    stamp = (meta.get("generated_at") or "")[:16].replace("T", " ")
    if stamp:
        teile.append(stamp)
    return " · ".join(teile) or "Suche"
