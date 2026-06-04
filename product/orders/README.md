# orders/ — Aufträge + Status (datei-basiert)

> Spec-only. Kein Code, keine Daten in dieser Runde.

Hier liegen später die strukturierten Aufträge und ihr Status — datei-basiert
(JSON), passend zum datei-basierten Ansatz der Engine.

## Inhalt (später)
- Pro Auftrag eine JSON-Datei nach `../operator/ORDER_SCHEMA.md`.
- Lebenszyklus: `entwurf → bestaetigt → laeuft → fertig` (V2: `wartet_auf_freigabe`).

## Regeln
- Speicherort über konfigurierbares `DATA_DIR` (siehe `../PACKAGING.md`, 2.2) —
  **nicht** hardcodiert, **nicht** im Programmordner.
- Keine Secrets in Auftragsdateien.
- Quelle der Wahrheit für die Mini-UI (lesend) und den Operator-Bericht.
