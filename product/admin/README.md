# admin/ — intern (Debug / Rohdaten / Support)

> Spec-only. Kein Code in dieser Runde.

**Nur intern.** Nichts hieraus erscheint je im Kundenfluss.

## Zweck
- Direkter Blick auf Engine-Output, Funnel-Diagnosen, Roh-Leads.
- Verweis auf bestehende interne Werkzeuge (NICHT ausliefern):
  - `../../b2bbot/cockpit_server.py` + Premium-Dashboard (Admin-Cockpit).
  - `../../b2bbot/run_intent_*.py` (Intent-Pipeline-Skripte).
  - `../../b2bbot/smoke_*.py` (Validierungs-Skripte).
- Support-/Fehlerbericht (später): redigiert, **ohne** Secrets
  (siehe `../PACKAGING.md`, 2.5).

## Regel
- Kundensicht geht **immer** durch Operator/Bridge.
- Admin greift direkt auf die Engine zu — der Kunde **nie**.
