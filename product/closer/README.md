# closer/ — Adapter-Konzept zu ClouseAgent (V2+)

> Spec-only. **In V1 absichtlich leer** (nur diese Doku).

Der Closer (`../../ClouseAgent/`) ist ein **eigenständiger** Live-Sales-Coach
(Mikro + STT + `sales_brain.py`). Er bleibt getrennt:

## Harte Trennung
- **Nicht** im B2B-Telegram-Fluss. Das `closing`-Feature im bestehenden
  `telegram_seller` bleibt aus (`features.closing = false`).
- **Nicht** mit dem B2B-MVP vermischen — eigene Bedienung, eigener Start.
- `ClouseAgent/` wird **nicht** verändert und **nicht** hierher kopiert.

## Wichtig: keine Hermes-Kopplung
- Das `voice_shell/`-Gerüst in `../../b2bbot/` referenziert in seinen Contracts
  „Hermes Prime → Sandra". Diese Kopplung wird **nicht** weitergebaut, damit
  nichts Richtung Hermes Prime / OpenClaw / Sandra wandert.

## Geplant (V2/V3)
- Optionaler Adapter: Closer über die Mini-UI startbar (nie über B2B-Telegram).
- Rückfluss Call-Ergebnis → Follow-up/CRM **nur** nach separater Freigabe.
- In V1 existiert hier bewusst kein Code.
